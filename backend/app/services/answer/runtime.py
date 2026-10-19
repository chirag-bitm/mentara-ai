from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID

from app.services.answer.context import (
    AnswerContextAssembler,
    BoundedAnswerContextAssembler,
)
from app.services.answer.lifecycle import AnswerLifecycle, InvalidAnswerTransition
from app.services.answer.models import (
    AnswerFailure,
    AnswerFailureCategory,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
    AnswerSessionSnapshot,
    AnswerSnapshot,
)
from app.services.answer.policy import AnswerPolicy, ConciseAnswerPolicy
from app.services.answer.provider import (
    AnswerProvider,
    AnswerProviderError,
    AnswerProviderRequest,
    AnswerProviderStream,
)
from app.services.answer.request import build_answer_request
from app.services.conversation.models import AssistanceDecision, ConversationTurn


logger = logging.getLogger(__name__)
AnswerEventSink = Callable[[AnswerSnapshot], None]


@dataclass(slots=True, frozen=True)
class AnswerSubmission:
    snapshot: AnswerSnapshot
    created: bool


class AnswerRuntime:
    """Logical-session-owned generation that never blocks the M3 callback."""

    def __init__(
        self,
        *,
        session_id: UUID,
        provider: AnswerProvider,
        clock: Callable[[], int],
        context_assembler: AnswerContextAssembler | None = None,
        policy: AnswerPolicy | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("answer timeout must be positive")
        self._session_id = session_id
        self._provider = provider
        self._clock = clock
        self._context_assembler = (
            context_assembler or BoundedAnswerContextAssembler()
        )
        self._policy = policy or ConciseAnswerPolicy()
        self._timeout_seconds = timeout_seconds
        self._lifecycles: dict[UUID, AnswerLifecycle] = {}
        self._active_answer_id: UUID | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._sink_id: UUID | None = None
        self._sink: AnswerEventSink | None = None

    @property
    def pending_task_count(self) -> int:
        return sum(not task.done() for task in self._tasks)

    def snapshot(self) -> AnswerSessionSnapshot:
        return AnswerSessionSnapshot(
            session_id=self._session_id,
            answers=tuple(
                lifecycle.snapshot for lifecycle in self._lifecycles.values()
            ),
            active_answer_id=self._active_answer_id,
        )

    def attach_sink(
        self,
        sink_id: UUID,
        sink: AnswerEventSink,
    ) -> AnswerSessionSnapshot:
        self._sink_id = sink_id
        self._sink = sink
        return self.snapshot()

    def detach_sink(self, sink_id: UUID) -> bool:
        if sink_id != self._sink_id:
            return False
        self._sink_id = None
        self._sink = None
        return True

    def request_answer(
        self,
        decision: AssistanceDecision,
        source_turn: ConversationTurn,
        *,
        recent_finalized_turns: Sequence[ConversationTurn],
    ) -> AnswerSubmission:
        if decision.session_id != self._session_id:
            raise ValueError("assistance decision belongs to another session")

        requested_ms = max(self._clock(), decision.detected_ms)
        request = build_answer_request(
            decision,
            source_turn,
            requested_ms=requested_ms,
        )
        existing = self._lifecycles.get(request.answer_id)
        if existing is not None:
            return AnswerSubmission(snapshot=existing.snapshot, created=False)

        now_ms = requested_ms
        if self._active_answer_id is not None:
            active = self._lifecycles[self._active_answer_id]
            if not active.snapshot.state.is_terminal:
                self._supersede_active(now_ms=now_ms)

        context = self._context_assembler.assemble(
            request,
            source_turn,
            recent_finalized_turns=recent_finalized_turns,
        )
        prompt = self._policy.build_prompt(request, context)
        lifecycle = AnswerLifecycle(request)
        self._lifecycles[request.answer_id] = lifecycle
        self._active_answer_id = request.answer_id
        provider_request = AnswerProviderRequest(
            answer_id=request.answer_id,
            attempt=request.attempt,
            prompt=prompt,
        )
        task = asyncio.create_task(
            self._run(request.answer_id, provider_request),
            name=f"answer-{request.answer_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        self._active_task = task
        return AnswerSubmission(snapshot=lifecycle.snapshot, created=True)

    def cancel_active(self, *, at_ms: int | None = None) -> AnswerSnapshot | None:
        answer_id = self._active_answer_id
        if answer_id is None:
            return None
        lifecycle = self._lifecycles[answer_id]
        if lifecycle.snapshot.state.is_terminal:
            self._clear_active(answer_id)
            return lifecycle.snapshot
        snapshot = lifecycle.cancel(at_ms=max(at_ms or self._clock(), lifecycle.snapshot.requested_ms))
        self._emit(snapshot)
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()
        self._clear_active(answer_id)
        return snapshot

    def shutdown_nowait(self) -> None:
        self.cancel_active()
        self._sink_id = None
        self._sink = None

    def reset(self, *, session_id: UUID) -> None:
        self.shutdown_nowait()
        self._session_id = session_id
        self._lifecycles.clear()

    async def wait_idle(self) -> None:
        tasks = tuple(self._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(
        self,
        answer_id: UUID,
        provider_request: AnswerProviderRequest,
    ) -> None:
        lifecycle = self._lifecycles[answer_id]
        stream: AnswerProviderStream | None = None
        expected_provider_sequence = 1
        saw_completion = False
        try:
            starting = lifecycle.mark_starting(
                at_ms=max(self._clock(), lifecycle.snapshot.requested_ms)
            )
            self._emit(starting)
            logger.info(
                "Answer provider starting: turn_sequence=%s "
                "answer_request_to_provider_start_ms=%s",
                starting.source_turn_sequence,
                starting.answer_request_to_provider_start_ms,
            )
            async with asyncio.timeout(self._timeout_seconds):
                stream = await self._provider.start(provider_request)
                async for event in stream:
                    if event.sequence != expected_provider_sequence:
                        raise AnswerProviderError(
                            AnswerFailureCategory.MALFORMED_STREAM,
                            "Answer provider returned an invalid stream.",
                            retryable=False,
                        )
                    expected_provider_sequence += 1
                    now_ms = max(self._clock(), lifecycle.snapshot.requested_ms)
                    if isinstance(event, AnswerProviderTextDelta):
                        snapshot = lifecycle.append_delta(
                            event.text,
                            sequence=lifecycle.snapshot.stream_sequence + 1,
                            at_ms=now_ms,
                        )
                        self._emit(snapshot)
                        if snapshot.stream_sequence == 1:
                            logger.info(
                                "First answer text received: turn_sequence=%s "
                                "answer_request_to_first_text_ms=%s "
                                "question_detected_to_first_text_ms=%s",
                                snapshot.source_turn_sequence,
                                snapshot.answer_request_to_first_text_ms,
                                snapshot.question_detected_to_first_text_ms,
                            )
                    elif isinstance(event, AnswerProviderCompleted):
                        snapshot = lifecycle.complete(
                            at_ms=now_ms,
                            usage=event.usage,
                        )
                        saw_completion = True
                        self._emit(snapshot)
                        logger.info(
                            "Answer generation completed: turn_sequence=%s "
                            "answer_generation_total_ms=%s input_tokens=%s "
                            "output_tokens=%s total_tokens=%s",
                            snapshot.source_turn_sequence,
                            snapshot.answer_generation_total_ms,
                            snapshot.usage.input_tokens if snapshot.usage else None,
                            snapshot.usage.output_tokens if snapshot.usage else None,
                            snapshot.usage.total_tokens if snapshot.usage else None,
                        )
                        break
                    else:
                        raise AnswerProviderError(
                            AnswerFailureCategory.MALFORMED_STREAM,
                            "Answer provider returned an unsupported stream event.",
                            retryable=False,
                        )
                if not saw_completion:
                    raise AnswerProviderError(
                        AnswerFailureCategory.MALFORMED_STREAM,
                        "Answer provider ended without completion.",
                        retryable=False,
                    )
        except asyncio.TimeoutError:
            self._fail_if_active(
                lifecycle,
                AnswerFailure(
                    category=AnswerFailureCategory.TIMEOUT,
                    safe_message="Answer generation timed out.",
                    retryable=True,
                ),
            )
        except AnswerProviderError as exc:
            self._fail_if_active(
                lifecycle,
                AnswerFailure(
                    category=exc.category,
                    safe_message=exc.safe_message,
                    retryable=exc.retryable,
                ),
            )
        except InvalidAnswerTransition:
            logger.exception("Invalid internal answer lifecycle transition")
            self._fail_if_active(
                lifecycle,
                AnswerFailure(
                    category=AnswerFailureCategory.MALFORMED_STREAM,
                    safe_message="Answer provider returned an invalid stream.",
                    retryable=False,
                ),
            )
        except asyncio.CancelledError:
            if not lifecycle.snapshot.state.is_terminal:
                snapshot = lifecycle.cancel(
                    at_ms=max(self._clock(), lifecycle.snapshot.requested_ms)
                )
                self._emit(snapshot)
            raise
        except Exception as exc:
            logger.error(
                "Unexpected answer provider failure: exception_type=%s",
                type(exc).__name__,
            )
            self._fail_if_active(
                lifecycle,
                AnswerFailure(
                    category=AnswerFailureCategory.UNKNOWN,
                    safe_message="Answer generation failed.",
                    retryable=False,
                ),
            )
        finally:
            if stream is not None:
                with suppress(Exception, asyncio.TimeoutError):
                    await asyncio.wait_for(stream.aclose(), timeout=1.0)
            self._clear_active(answer_id)

    def _supersede_active(self, *, now_ms: int) -> None:
        answer_id = self._active_answer_id
        if answer_id is None:
            return
        lifecycle = self._lifecycles[answer_id]
        snapshot = lifecycle.supersede(
            at_ms=max(now_ms, lifecycle.snapshot.requested_ms)
        )
        self._emit(snapshot)
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()
        self._clear_active(answer_id)

    def _fail_if_active(
        self,
        lifecycle: AnswerLifecycle,
        failure: AnswerFailure,
    ) -> None:
        if lifecycle.snapshot.state.is_terminal:
            return
        snapshot = lifecycle.fail(
            failure,
            at_ms=max(self._clock(), lifecycle.snapshot.requested_ms),
        )
        self._emit(snapshot)
        logger.warning(
            "Answer generation failed: turn_sequence=%s category=%s "
            "had_visible_text=%s",
            snapshot.source_turn_sequence,
            failure.category.value,
            bool(snapshot.text),
        )

    def _emit(self, snapshot: AnswerSnapshot) -> None:
        sink = self._sink
        if sink is None:
            return
        try:
            sink(snapshot)
        except Exception:
            logger.exception("Answer event sink rejected an update")

    def _clear_active(self, answer_id: UUID) -> None:
        if self._active_answer_id == answer_id:
            self._active_answer_id = None
            self._active_task = None

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        with suppress(asyncio.CancelledError):
            task.result()
