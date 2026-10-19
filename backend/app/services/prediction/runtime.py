from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.services.conversation.models import ActiveConversationTurn, ContinuityQuality
from app.services.memory.models import MemoryContinuity, MemorySnapshot
from app.services.prediction.context import (
    DeterministicPredictionContextPlanner,
    PredictionContextPlanner,
)
from app.services.prediction.compatibility import (
    ConservativeAppendOnlyPredictionCompatibilityPolicy,
    PredictionInputCompatibilityLimits,
    PredictionInputCompatibilityPolicy,
)
from app.services.prediction.identity import (
    derive_prediction_id,
    derive_prediction_input_fingerprint,
    normalize_prediction_input_text,
)
from app.services.prediction.lifecycle import (
    InvalidPredictionTransition,
    PredictionLifecycle,
)
from app.services.prediction.models import (
    PredictionFailure,
    PredictionFailureCategory,
    PredictionInvalidationReason,
    PredictionContext,
    PredictionContextTurn,
    PredictionSessionSnapshot,
    PredictionSnapshot,
    PredictionState,
    PredictionTriggerReason,
)
from app.services.prediction.provider import (
    PredictionProviderError,
    PredictionProviderResult,
)
from app.services.transcript.models import CanonicalUtterance
from app.services.prediction.trigger import (
    DeterministicPredictionTriggerPolicy,
    PredictionTriggerPolicy,
)


logger = logging.getLogger(__name__)
PredictionEventSink = Callable[[PredictionSnapshot], None]
MemorySnapshotSupplier = Callable[[], MemorySnapshot | None]


@dataclass(slots=True, frozen=True)
class PredictionRuntimeLimits:
    coalesce_seconds: float
    provider_timeout_seconds: float
    max_attempts_per_turn: int
    max_calls_per_session: int
    cancelled_attempt_cooldown_seconds: float = 0
    max_compatible_extension_chars: int = 0

    def __post_init__(self) -> None:
        if self.coalesce_seconds < 0:
            raise ValueError("prediction coalescing delay must not be negative")
        if self.cancelled_attempt_cooldown_seconds < 0:
            raise ValueError("prediction cancellation cooldown must not be negative")
        if self.max_compatible_extension_chars < 0:
            raise ValueError("compatible extension limit must not be negative")
        if self.max_compatible_extension_chars > 512:
            raise ValueError("compatible extension limit must not exceed 512")
        if self.provider_timeout_seconds <= 0:
            raise ValueError("prediction provider timeout must be positive")
        if self.max_attempts_per_turn < 1:
            raise ValueError("prediction turn attempt limit must be positive")
        if self.max_calls_per_session < self.max_attempts_per_turn:
            raise ValueError("prediction session limit cannot be below turn limit")


@dataclass(slots=True, frozen=True)
class PredictionAttemptInput:
    prediction_id: UUID
    session_id: UUID
    active_turn: ActiveConversationTurn
    triggering_utterance: CanonicalUtterance
    input_revision: int
    attempt: int
    material_fingerprint: str
    memory_revision: int
    observed_ms: int
    context: PredictionContext

    def __post_init__(self) -> None:
        if self.session_id != self.active_turn.session_id:
            raise ValueError("prediction attempt active turn belongs to another session")
        if self.triggering_utterance.session_id != self.session_id:
            raise ValueError("prediction attempt utterance belongs to another session")
        if self.prediction_id != derive_prediction_id(
            self.session_id,
            self.active_turn.turn_id,
        ):
            raise ValueError("prediction attempt identity does not match active turn")
        if self.input_revision < 1 or self.attempt < 1:
            raise ValueError("prediction attempt revision/attempt must be positive")
        if self.memory_revision < 0:
            raise ValueError("prediction attempt memory revision must not be negative")
        if self.observed_ms < self.active_turn.last_updated_ms:
            raise ValueError("prediction attempt observation cannot precede active input")
        if self.triggering_utterance.utterance_id not in (
            self.active_turn.source_utterance_ids
        ):
            raise ValueError("prediction attempt utterance is not in the active turn")
        index = self.active_turn.source_utterance_ids.index(
            self.triggering_utterance.utterance_id
        )
        if (
            self.active_turn.source_transcript_sequences[index]
            != self.triggering_utterance.sequence
        ):
            raise ValueError("prediction attempt transcript provenance does not match")
        expected_fingerprint = derive_prediction_input_fingerprint(
            self.active_turn,
            memory_revision=self.memory_revision,
        )
        if self.material_fingerprint != expected_fingerprint:
            raise ValueError("prediction attempt fingerprint does not match its input")
        if self.context.session_id != self.session_id:
            raise ValueError("prediction attempt context belongs to another session")
        if self.context.prediction_id != self.prediction_id:
            raise ValueError("prediction attempt context identity does not match")
        if self.context.input_revision != self.input_revision:
            raise ValueError("prediction attempt context input revision does not match")
        if self.context.memory_revision != self.memory_revision:
            raise ValueError("prediction attempt context memory revision does not match")
        context_active = self.context.active_turn
        if (
            not _context_active_matches(context_active, self.active_turn)
        ):
            raise ValueError("prediction attempt context active provenance does not match")


class PredictionAttemptExecutor(Protocol):
    """Application seam that Phase D will back with a prediction provider."""

    async def execute(
        self,
        attempt: PredictionAttemptInput,
    ) -> PredictionProviderResult: ...


@dataclass(slots=True, frozen=True)
class PredictionSubmission:
    snapshot: PredictionSessionSnapshot
    materially_changed: bool
    scheduled: bool
    trigger_reason: PredictionTriggerReason


@dataclass(slots=True, frozen=True)
class _Observation:
    active_turn: ActiveConversationTurn
    triggering_utterance: CanonicalUtterance
    input_revision: int
    material_fingerprint: str
    memory_revision: int
    observed_ms: int
    earliest_attempt_ms: int
    generation: int
    basis_text: str


class PredictionRuntime:
    """Logical-session side-car with one latest slot and bounded async work."""

    def __init__(
        self,
        *,
        session_id: UUID,
        executor: PredictionAttemptExecutor,
        clock: Callable[[], int],
        limits: PredictionRuntimeLimits,
        trigger_policy: PredictionTriggerPolicy | None = None,
        context_planner: PredictionContextPlanner | None = None,
        memory_snapshot_supplier: MemorySnapshotSupplier | None = None,
        input_compatibility_policy: PredictionInputCompatibilityPolicy | None = None,
    ) -> None:
        self._session_id = session_id
        self._executor = executor
        self._clock = clock
        self._limits = limits
        self._trigger_policy = (
            trigger_policy or DeterministicPredictionTriggerPolicy()
        )
        self._context_planner = (
            context_planner or DeterministicPredictionContextPlanner()
        )
        self._memory_snapshot_supplier = memory_snapshot_supplier
        self._input_compatibility_policy = (
            input_compatibility_policy
            or ConservativeAppendOnlyPredictionCompatibilityPolicy(
                limits=PredictionInputCompatibilityLimits(
                    max_extension_chars=limits.max_compatible_extension_chars
                )
            )
        )
        self._lifecycle: PredictionLifecycle | None = None
        self._observation: _Observation | None = None
        self._prediction_id: UUID | None = None
        self._input_revision = 0
        self._turn_attempt_count = 0
        self._turn_compatible_extension_count = 0
        self._snapshot_revision = 0
        self._generation = 0
        self._provider_attempt_count = 0
        self._stale_discard_count = 0
        self._cancelled_call_count = 0
        self._suppressed_observation_count = 0
        self._last_trigger_reason: PredictionTriggerReason | None = None
        self._last_provider_started_ms: int | None = None
        self._last_cancelled_attempt_ms: int | None = None
        self._candidate_counts: dict[tuple[str, str], int] = {}
        self._last_ready_input_revision: int | None = None
        self._browser_attached = True
        self._shutdown = False
        self._work_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._provider_task: asyncio.Task[PredictionProviderResult] | None = None
        self._provider_cancel_requested = False
        self._sink_id: UUID | None = None
        self._sink: PredictionEventSink | None = None

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def pending_task_count(self) -> int:
        tasks = {self._worker_task, self._provider_task}
        return sum(task is not None and not task.done() for task in tasks)

    @property
    def active_provider_task_count(self) -> int:
        task = self._provider_task
        return int(task is not None and not task.done())

    @property
    def turn_attempt_count(self) -> int:
        return self._turn_attempt_count

    @property
    def turn_compatible_extension_count(self) -> int:
        return self._turn_compatible_extension_count

    def snapshot(self) -> PredictionSessionSnapshot:
        current = self._lifecycle.snapshot if self._lifecycle is not None else None
        return PredictionSessionSnapshot(
            session_id=self._session_id,
            state=current.state if current is not None else PredictionState.IDLE,
            current=current,
            provider_attempt_count=self._provider_attempt_count,
            stale_discard_count=self._stale_discard_count,
            cancelled_call_count=self._cancelled_call_count,
            suppressed_observation_count=self._suppressed_observation_count,
            last_trigger_reason=self._last_trigger_reason,
        )

    def attach_sink(
        self,
        sink_id: UUID,
        sink: PredictionEventSink,
    ) -> PredictionSessionSnapshot:
        self._sink_id = sink_id
        self._sink = sink
        return self.snapshot()

    def detach_sink(self, sink_id: UUID) -> bool:
        if sink_id != self._sink_id:
            return False
        self._sink_id = None
        self._sink = None
        return True

    def attach_browser(self) -> PredictionSessionSnapshot:
        if self._shutdown:
            raise RuntimeError("prediction runtime is shut down")
        self._browser_attached = True
        return self.snapshot()

    def observe_nowait(
        self,
        active_turn: ActiveConversationTurn,
        triggering_utterance: CanonicalUtterance,
        *,
        memory_revision: int,
    ) -> PredictionSubmission:
        if self._shutdown:
            raise RuntimeError("prediction runtime is shut down")
        if not self._browser_attached:
            return PredictionSubmission(
                snapshot=self.snapshot(),
                materially_changed=False,
                scheduled=False,
                trigger_reason=PredictionTriggerReason.BROWSER_DETACHED,
            )
        self._validate_observation(
            active_turn,
            triggering_utterance,
            memory_revision=memory_revision,
        )
        fingerprint = derive_prediction_input_fingerprint(
            active_turn,
            memory_revision=memory_revision,
        )
        observed_ms = max(self._clock(), active_turn.last_updated_ms)
        prediction_id = derive_prediction_id(self._session_id, active_turn.turn_id)
        previous = self._observation

        if self._prediction_id == prediction_id and previous is not None:
            previous_active_fingerprint = derive_prediction_input_fingerprint(
                previous.active_turn,
                memory_revision=previous.memory_revision,
            )
            if previous_active_fingerprint == fingerprint:
                self._observation = _Observation(
                    active_turn=active_turn,
                    triggering_utterance=triggering_utterance,
                    input_revision=previous.input_revision,
                    material_fingerprint=previous.material_fingerprint,
                    memory_revision=memory_revision,
                    observed_ms=observed_ms,
                    earliest_attempt_ms=previous.earliest_attempt_ms,
                    generation=previous.generation,
                    basis_text=previous.basis_text,
                )
                self._last_trigger_reason = PredictionTriggerReason.UNCHANGED
                self._refresh_active_state(active_turn)
                return PredictionSubmission(
                    snapshot=self.snapshot(),
                    materially_changed=False,
                    scheduled=False,
                    trigger_reason=PredictionTriggerReason.UNCHANGED,
                )
            if self._can_preserve_current_attempt(
                previous,
                active_turn,
                memory_revision=memory_revision,
            ):
                self._observation = _Observation(
                    active_turn=active_turn,
                    triggering_utterance=triggering_utterance,
                    input_revision=previous.input_revision,
                    material_fingerprint=previous.material_fingerprint,
                    memory_revision=previous.memory_revision,
                    observed_ms=previous.observed_ms,
                    earliest_attempt_ms=previous.earliest_attempt_ms,
                    generation=previous.generation,
                    basis_text=previous.basis_text,
                )
                self._last_trigger_reason = (
                    PredictionTriggerReason.COMPATIBLE_EXTENSION
                )
                self._turn_compatible_extension_count += 1
                self._refresh_active_state(active_turn)
                return PredictionSubmission(
                    snapshot=self.snapshot(),
                    materially_changed=False,
                    scheduled=False,
                    trigger_reason=PredictionTriggerReason.COMPATIBLE_EXTENSION,
                )
            reason = self._change_reason(previous, active_turn, memory_revision)
            if self._cancel_provider_nowait(reason=reason):
                self._last_cancelled_attempt_ms = observed_ms
            self._invalidate_current(reason, at_ms=observed_ms)
            self._input_revision += 1
            if reason in {
                PredictionInvalidationReason.SOURCE_OR_SPEAKER_CHANGED,
                PredictionInvalidationReason.MEMORY_REVISION_CHANGED,
                PredictionInvalidationReason.CONTINUITY_DEGRADED,
            }:
                self._reset_candidate_consistency()
        else:
            if self._lifecycle is not None:
                self._generation += 1
                self._cancel_provider_nowait(
                    reason=PredictionInvalidationReason.NEW_ACTIVE_TURN
                )
                self._invalidate_current(
                    PredictionInvalidationReason.NEW_ACTIVE_TURN,
                    at_ms=observed_ms,
                )
            self._prediction_id = prediction_id
            self._input_revision = 1
            self._turn_attempt_count = 0
            self._turn_compatible_extension_count = 0
            self._last_cancelled_attempt_ms = None
            self._snapshot_revision = 0
            self._reset_candidate_consistency()

        trigger = self._trigger_policy.evaluate(
            active_turn,
            triggering_utterance,
            observed_ms=observed_ms,
            last_attempt_started_ms=self._last_provider_started_ms,
        )
        self._last_trigger_reason = trigger.reason
        self._generation += 1
        observation = _Observation(
            active_turn=active_turn,
            triggering_utterance=triggering_utterance,
            input_revision=self._input_revision,
            material_fingerprint=fingerprint,
            memory_revision=memory_revision,
            observed_ms=observed_ms,
            earliest_attempt_ms=max(
                trigger.earliest_attempt_ms or observed_ms,
                (
                    self._last_cancelled_attempt_ms
                    + round(self._limits.cancelled_attempt_cooldown_seconds * 1_000)
                    if self._last_cancelled_attempt_ms is not None
                    else observed_ms
                ),
            ),
            generation=self._generation,
            basis_text=active_turn.text,
        )
        self._observation = observation

        if not trigger.eligible:
            self._suppressed_observation_count += 1
            if trigger.reason is PredictionTriggerReason.CONTINUITY_UNSAFE:
                self._lifecycle = PredictionLifecycle(
                    self._scheduled_snapshot(observation, prediction_id)
                )
                self._emit(self._lifecycle.snapshot)
                self._reset_candidate_consistency()
                self._invalidate_current(
                    PredictionInvalidationReason.CONTINUITY_DEGRADED,
                    at_ms=observed_ms,
                )
            logger.info(
                "Prediction observation suppressed: turn_sequence=%s "
                "input_revision=%s reason=%s",
                active_turn.turn_sequence,
                observation.input_revision,
                trigger.reason.value,
            )
            return PredictionSubmission(
                snapshot=self.snapshot(),
                materially_changed=True,
                scheduled=False,
                trigger_reason=trigger.reason,
            )

        self._lifecycle = PredictionLifecycle(
            self._scheduled_snapshot(observation, prediction_id)
        )
        self._emit(self._lifecycle.snapshot)

        if self._provider_attempt_count >= self._limits.max_calls_per_session:
            self._last_trigger_reason = PredictionTriggerReason.SESSION_CALL_LIMIT
            self._invalidate_current(
                PredictionInvalidationReason.SESSION_CALL_LIMIT,
                at_ms=observed_ms,
            )
            return PredictionSubmission(
                self.snapshot(),
                True,
                False,
                PredictionTriggerReason.SESSION_CALL_LIMIT,
            )
        if self._turn_attempt_count >= self._limits.max_attempts_per_turn:
            self._last_trigger_reason = PredictionTriggerReason.TURN_ATTEMPT_LIMIT
            self._invalidate_current(
                PredictionInvalidationReason.TURN_ATTEMPT_LIMIT,
                at_ms=observed_ms,
            )
            return PredictionSubmission(
                self.snapshot(),
                True,
                False,
                PredictionTriggerReason.TURN_ATTEMPT_LIMIT,
            )

        self._work_event.set()
        self._ensure_worker()
        return PredictionSubmission(
            snapshot=self.snapshot(),
            materially_changed=True,
            scheduled=True,
            trigger_reason=trigger.reason,
        )

    def invalidate_turn_nowait(
        self,
        turn_id: UUID,
        *,
        reason: PredictionInvalidationReason,
        at_ms: int | None = None,
    ) -> PredictionSnapshot | None:
        lifecycle = self._lifecycle
        if lifecycle is None or lifecycle.snapshot.active_turn_id != turn_id:
            return None
        self._generation += 1
        self._cancel_provider_nowait(reason=reason)
        self._work_event.set()
        self._observation = None
        self._reset_candidate_consistency()
        return self._invalidate_current(
            reason,
            at_ms=self._clock() if at_ms is None else at_ms,
        )

    def mark_continuity_degraded_nowait(self) -> PredictionSnapshot | None:
        lifecycle = self._lifecycle
        if lifecycle is None:
            return None
        return self.invalidate_turn_nowait(
            lifecycle.snapshot.active_turn_id,
            reason=PredictionInvalidationReason.CONTINUITY_DEGRADED,
        )

    async def disconnect(self) -> None:
        self._browser_attached = False
        self._clear_nowait(PredictionInvalidationReason.BROWSER_DISCONNECTED)
        self._sink_id = None
        self._sink = None
        await self.wait_idle()

    def reset(self, *, session_id: UUID) -> None:
        self._clear_nowait(PredictionInvalidationReason.SESSION_RESET)
        self._session_id = session_id
        self._provider_attempt_count = 0
        self._stale_discard_count = 0
        self._cancelled_call_count = 0
        self._suppressed_observation_count = 0
        self._last_trigger_reason = None
        self._last_provider_started_ms = None
        self._last_cancelled_attempt_ms = None
        self._browser_attached = True
        self._shutdown = False

    def shutdown_nowait(
        self,
        *,
        reason: PredictionInvalidationReason = (
            PredictionInvalidationReason.STOP_REQUESTED
        ),
    ) -> None:
        self._shutdown = True
        self._browser_attached = False
        self._clear_nowait(reason)
        self._sink_id = None
        self._sink = None

    async def wait_idle(self) -> None:
        while True:
            tasks = tuple(
                task
                for task in {self._worker_task, self._provider_task}
                if task is not None and not task.done()
            )
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0)

    async def _run_worker(self) -> None:
        try:
            while not self._shutdown and self._browser_attached:
                self._work_event.clear()
                generation = self._generation
                observation = self._observation
                if observation is None:
                    return
                coalesce_deadline_ms = observation.observed_ms + round(
                    self._limits.coalesce_seconds * 1_000
                )
                wake_at_ms = max(
                    coalesce_deadline_ms,
                    observation.earliest_attempt_ms,
                )
                delay_seconds = max(0, wake_at_ms - self._clock()) / 1_000
                if delay_seconds > 0:
                    try:
                        await asyncio.wait_for(
                            self._work_event.wait(),
                            timeout=delay_seconds,
                        )
                    except TimeoutError:
                        pass
                    else:
                        continue
                else:
                    await asyncio.sleep(0)
                    if self._work_event.is_set():
                        continue

                observation = self._observation
                lifecycle = self._lifecycle
                if (
                    observation is None
                    or lifecycle is None
                    or lifecycle.snapshot.state is not PredictionState.SCHEDULED
                    or observation.generation != generation
                ):
                    if self._work_event.is_set():
                        continue
                    return

                if (
                    self._provider_attempt_count
                    >= self._limits.max_calls_per_session
                ):
                    self._invalidate_current(
                        PredictionInvalidationReason.SESSION_CALL_LIMIT,
                        at_ms=self._clock(),
                    )
                    return
                if self._turn_attempt_count >= self._limits.max_attempts_per_turn:
                    self._invalidate_current(
                        PredictionInvalidationReason.TURN_ATTEMPT_LIMIT,
                        at_ms=self._clock(),
                    )
                    return

                context = self._prepare_context(observation)
                if context is None:
                    return

                attempt_number = self._turn_attempt_count + 1
                self._turn_attempt_count = attempt_number
                self._provider_attempt_count += 1
                running = lifecycle.mark_running(
                    attempt=attempt_number,
                    at_ms=max(self._clock(), lifecycle.snapshot.input_observed_ms),
                    context_chars=context.total_text_chars,
                )
                self._last_provider_started_ms = running.provider_started_ms
                self._snapshot_revision = running.snapshot_revision
                self._emit(running)
                attempt = PredictionAttemptInput(
                    prediction_id=running.prediction_id,
                    session_id=running.session_id,
                    active_turn=observation.active_turn,
                    triggering_utterance=observation.triggering_utterance,
                    input_revision=observation.input_revision,
                    attempt=attempt_number,
                    material_fingerprint=observation.material_fingerprint,
                    memory_revision=observation.memory_revision,
                    observed_ms=observation.observed_ms,
                    context=context,
                )
                logger.info(
                    "Prediction attempt started: turn_sequence=%s "
                    "input_revision=%s attempt=%s session_attempt_count=%s "
                    "prediction_context_chars=%s",
                    running.active_turn_sequence,
                    running.input_revision,
                    running.attempt,
                    self._provider_attempt_count,
                    context.total_text_chars,
                )
                self._provider_cancel_requested = False
                provider_task = asyncio.create_task(
                    self._executor.execute(attempt),
                    name=f"prediction-attempt-{running.prediction_id}",
                )
                self._provider_task = provider_task
                try:
                    result = await asyncio.wait_for(
                        provider_task,
                        timeout=self._limits.provider_timeout_seconds,
                    )
                except TimeoutError:
                    self._cancelled_call_count += 1
                    self._fail_if_current(
                        attempt,
                        PredictionFailure(
                            category=PredictionFailureCategory.TIMEOUT,
                            safe_message="Prediction timed out.",
                            retryable=True,
                        ),
                    )
                    return
                except PredictionProviderError as exc:
                    self._fail_if_current(
                        attempt,
                        PredictionFailure(
                            category=exc.category,
                            safe_message=exc.safe_message,
                            retryable=exc.retryable,
                        ),
                    )
                    return
                except asyncio.CancelledError:
                    worker = asyncio.current_task()
                    if worker is not None and worker.cancelling():
                        raise
                    if self._work_event.is_set():
                        continue
                    return
                except Exception as exc:
                    logger.error(
                        "Unexpected prediction attempt failure: exception_type=%s",
                        type(exc).__name__,
                    )
                    self._fail_if_current(
                        attempt,
                        PredictionFailure(
                            category=PredictionFailureCategory.UNKNOWN,
                            safe_message="Prediction failed.",
                            retryable=False,
                        ),
                    )
                    return
                finally:
                    if self._provider_task is provider_task:
                        self._provider_task = None
                        self._provider_cancel_requested = False

                if not isinstance(result, PredictionProviderResult):
                    self._fail_if_current(
                        attempt,
                        PredictionFailure(
                            category=PredictionFailureCategory.MALFORMED_OUTPUT,
                            safe_message="Prediction provider returned invalid output.",
                            retryable=False,
                        ),
                    )
                    return
                if not self._is_current(attempt):
                    self._stale_discard_count += 1
                    logger.info(
                        "Stale prediction result discarded: turn_sequence=%s "
                        "input_revision=%s attempt=%s",
                        attempt.active_turn.turn_sequence,
                        attempt.input_revision,
                        attempt.attempt,
                    )
                    if self._work_event.is_set():
                        continue
                    return

                consistent_count = self._record_candidate_consistency(
                    result,
                    input_revision=attempt.input_revision,
                )
                try:
                    ready = lifecycle.mark_ready(
                        candidates=result.candidates,
                        consistent_revision_count=consistent_count,
                        at_ms=max(self._clock(), running.provider_started_ms or 0),
                        usage=result.usage,
                    )
                except InvalidPredictionTransition:
                    self._stale_discard_count += 1
                    if self._work_event.is_set():
                        continue
                    return
                self._snapshot_revision = ready.snapshot_revision
                self._emit(ready)
                logger.info(
                    "Prediction ready: turn_sequence=%s input_revision=%s "
                    "attempt=%s readiness=%s candidate_count=%s "
                    "prediction_request_to_ready_ms=%s input_tokens=%s "
                    "output_tokens=%s total_tokens=%s",
                    ready.active_turn_sequence,
                    ready.input_revision,
                    ready.attempt,
                    ready.readiness.value if ready.readiness is not None else None,
                    len(ready.candidates),
                    ready.prediction_request_to_ready_ms,
                    ready.usage.input_tokens if ready.usage else None,
                    ready.usage.output_tokens if ready.usage else None,
                    ready.usage.total_tokens if ready.usage else None,
                )
                if self._work_event.is_set():
                    continue
                return
        finally:
            provider_task = self._provider_task
            if provider_task is not None and not provider_task.done():
                provider_task.cancel()
                with suppress(asyncio.CancelledError):
                    await provider_task
            current = asyncio.current_task()
            if self._worker_task is current:
                self._worker_task = None
                if (
                    self._work_event.is_set()
                    and not self._shutdown
                    and self._browser_attached
                ):
                    self._ensure_worker()

    def _scheduled_snapshot(
        self,
        observation: _Observation,
        prediction_id: UUID,
    ) -> PredictionSnapshot:
        self._snapshot_revision += 1
        active = observation.active_turn
        return PredictionSnapshot(
            prediction_id=prediction_id,
            session_id=self._session_id,
            active_turn_id=active.turn_id,
            active_turn_sequence=active.turn_sequence,
            input_revision=observation.input_revision,
            attempt=self._turn_attempt_count,
            state=PredictionState.SCHEDULED,
            snapshot_revision=self._snapshot_revision,
            material_fingerprint=observation.material_fingerprint,
            memory_revision=observation.memory_revision,
            audio_source=active.audio_source,
            speaker_role=active.speaker_role,
            continuity_quality=active.continuity_quality,
            active_turn_awaiting_finalization=active.awaiting_finalization,
            candidate_consistent_revision_count=0,
            candidates=(),
            input_observed_ms=observation.observed_ms,
            scheduled_ms=observation.observed_ms,
        )

    def _prepare_context(
        self,
        observation: _Observation,
    ) -> PredictionContext | None:
        try:
            snapshot = (
                self._memory_snapshot_supplier()
                if self._memory_snapshot_supplier is not None
                else None
            )
        except Exception as exc:
            logger.error(
                "Prediction memory snapshot unavailable: exception_type=%s",
                type(exc).__name__,
            )
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None

        if snapshot is None:
            snapshot = MemorySnapshot(
                session_id=self._session_id,
                memory_revision=observation.memory_revision,
                entries=(),
                stored_turn_count=0,
                stored_text_chars=0,
                continuity=MemoryContinuity.NORMAL,
                evicted_turn_count=0,
                evicted_through_turn_sequence=None,
                missing_turn_count=0,
                latest_sequence_gap=None,
            )
        if not isinstance(snapshot, MemorySnapshot):
            logger.error("Prediction memory snapshot has an invalid type")
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None
        if snapshot.session_id != self._session_id:
            logger.error("Prediction memory snapshot belongs to another session")
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None
        if snapshot.memory_revision != observation.memory_revision:
            logger.info(
                "Prediction memory revision changed before context preparation: "
                "expected_revision=%s current_revision=%s",
                observation.memory_revision,
                snapshot.memory_revision,
            )
            self._reset_candidate_consistency()
            self._invalidate_context(
                PredictionInvalidationReason.MEMORY_REVISION_CHANGED
            )
            return None
        try:
            context = self._context_planner.plan(
                snapshot,
                observation.active_turn,
                input_revision=observation.input_revision,
            )
        except Exception as exc:
            logger.error(
                "Prediction context planning failed: exception_type=%s",
                type(exc).__name__,
            )
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None
        if not isinstance(context, PredictionContext):
            logger.error("Prediction context planner returned an invalid type")
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None
        if (
            context.session_id != self._session_id
            or context.prediction_id != self._prediction_id
            or context.input_revision != observation.input_revision
            or context.memory_revision != observation.memory_revision
            or not _context_active_matches(
                context.active_turn,
                observation.active_turn,
            )
        ):
            logger.error("Prediction context planner returned mismatched provenance")
            self._invalidate_context(
                PredictionInvalidationReason.CONTEXT_UNAVAILABLE
            )
            return None
        return context

    def _invalidate_context(self, reason: PredictionInvalidationReason) -> None:
        self._generation += 1
        self._observation = None
        self._work_event.clear()
        self._invalidate_current(reason, at_ms=self._clock())

    def _refresh_active_state(self, active_turn: ActiveConversationTurn) -> None:
        lifecycle = self._lifecycle
        if lifecycle is None or lifecycle.snapshot.state not in {
            PredictionState.SCHEDULED,
            PredictionState.RUNNING,
            PredictionState.READY,
        }:
            return
        previous = lifecycle.snapshot
        refreshed = lifecycle.refresh_active_state(
            awaiting_finalization=active_turn.awaiting_finalization,
            continuity_quality=active_turn.continuity_quality,
        )
        self._snapshot_revision = refreshed.snapshot_revision
        if refreshed is not previous:
            self._emit(refreshed)

    def _record_candidate_consistency(
        self,
        result: PredictionProviderResult,
        *,
        input_revision: int,
    ) -> int:
        keys = {
            (candidate.kind.value, normalize_prediction_input_text(candidate.text))
            for candidate in result.candidates
        }
        if not keys:
            self._reset_candidate_consistency()
            self._last_ready_input_revision = input_revision
            return 0
        if self._last_ready_input_revision == input_revision:
            counts = {key: self._candidate_counts.get(key, 1) for key in keys}
        else:
            counts = {key: self._candidate_counts.get(key, 0) + 1 for key in keys}
        self._candidate_counts = counts
        self._last_ready_input_revision = input_revision
        return max(counts.values())

    def _is_current(self, attempt: PredictionAttemptInput) -> bool:
        observation = self._observation
        lifecycle = self._lifecycle
        return bool(
            observation is not None
            and lifecycle is not None
            and lifecycle.snapshot.state is PredictionState.RUNNING
            and attempt.prediction_id == self._prediction_id
            and attempt.input_revision == observation.input_revision
            and attempt.attempt == lifecycle.snapshot.attempt
            and attempt.material_fingerprint == observation.material_fingerprint
            and attempt.memory_revision == observation.memory_revision
            and attempt.active_turn.turn_id == observation.active_turn.turn_id
        )

    def _fail_if_current(
        self,
        attempt: PredictionAttemptInput,
        failure: PredictionFailure,
    ) -> None:
        if not self._is_current(attempt):
            self._stale_discard_count += 1
            return
        lifecycle = self._lifecycle
        if lifecycle is None:
            return
        try:
            failed = lifecycle.fail(
                failure,
                at_ms=max(self._clock(), lifecycle.snapshot.input_observed_ms),
            )
        except InvalidPredictionTransition:
            self._stale_discard_count += 1
            return
        self._snapshot_revision = failed.snapshot_revision
        self._emit(failed)
        logger.warning(
            "Prediction failed: turn_sequence=%s input_revision=%s "
            "attempt=%s category=%s",
            failed.active_turn_sequence,
            failed.input_revision,
            failed.attempt,
            failure.category.value,
        )

    def _invalidate_current(
        self,
        reason: PredictionInvalidationReason,
        *,
        at_ms: int,
    ) -> PredictionSnapshot | None:
        lifecycle = self._lifecycle
        if lifecycle is None:
            return None
        previous = lifecycle.snapshot
        invalidated = lifecycle.invalidate(
            reason,
            at_ms=max(at_ms, previous.input_observed_ms),
        )
        self._snapshot_revision = invalidated.snapshot_revision
        if invalidated is not previous:
            self._emit(invalidated)
        return invalidated

    def _change_reason(
        self,
        previous: _Observation,
        active_turn: ActiveConversationTurn,
        memory_revision: int,
    ) -> PredictionInvalidationReason:
        prior = previous.active_turn
        if (
            prior.audio_source is not active_turn.audio_source
            or prior.speaker_role is not active_turn.speaker_role
        ):
            return PredictionInvalidationReason.SOURCE_OR_SPEAKER_CHANGED
        if memory_revision != previous.memory_revision:
            return PredictionInvalidationReason.MEMORY_REVISION_CHANGED
        if active_turn.continuity_quality is ContinuityQuality.DEGRADED:
            return PredictionInvalidationReason.CONTINUITY_DEGRADED
        if (
            prior.source_utterance_ids != active_turn.source_utterance_ids
        ):
            return PredictionInvalidationReason.ACTIVE_PROVENANCE_CHANGED
        return PredictionInvalidationReason.ACTIVE_INPUT_CHANGED

    def _can_preserve_current_attempt(
        self,
        previous: _Observation,
        active_turn: ActiveConversationTurn,
        *,
        memory_revision: int,
    ) -> bool:
        lifecycle = self._lifecycle
        if lifecycle is None or lifecycle.snapshot.state not in {
            PredictionState.RUNNING,
            PredictionState.READY,
        }:
            return False
        prior = previous.active_turn
        if (
            prior.audio_source is not active_turn.audio_source
            or prior.speaker_role is not active_turn.speaker_role
            or prior.source_utterance_ids != active_turn.source_utterance_ids
            or memory_revision != previous.memory_revision
            or active_turn.continuity_quality is not ContinuityQuality.NORMAL
        ):
            return False
        return self._input_compatibility_policy.allows_extension(
            previous.basis_text,
            active_turn.text,
        )

    def _validate_observation(
        self,
        active_turn: ActiveConversationTurn,
        triggering_utterance: CanonicalUtterance,
        *,
        memory_revision: int,
    ) -> None:
        if active_turn.session_id != self._session_id:
            raise ValueError("active turn belongs to another prediction session")
        if triggering_utterance.session_id != self._session_id:
            raise ValueError("triggering utterance belongs to another session")
        if memory_revision < 0:
            raise ValueError("prediction memory revision must not be negative")
        if triggering_utterance.utterance_id not in active_turn.source_utterance_ids:
            raise ValueError("triggering utterance is not part of the active turn")
        index = active_turn.source_utterance_ids.index(
            triggering_utterance.utterance_id
        )
        if active_turn.source_transcript_sequences[index] != (
            triggering_utterance.sequence
        ):
            raise ValueError("triggering transcript sequence does not match")
        if (
            triggering_utterance.audio_source is not active_turn.audio_source
            or triggering_utterance.speaker_role is not active_turn.speaker_role
        ):
            raise ValueError("triggering source/speaker does not match active turn")

    def _ensure_worker(self) -> None:
        task = self._worker_task
        if task is not None and not task.done():
            return
        self._worker_task = asyncio.create_task(
            self._run_worker(),
            name=f"prediction-worker-{self._session_id}",
        )

    def _cancel_provider_nowait(
        self, *, reason: PredictionInvalidationReason
    ) -> bool:
        task = self._provider_task
        if (
            task is not None
            and not task.done()
            and not self._provider_cancel_requested
        ):
            self._provider_cancel_requested = True
            self._cancelled_call_count += 1
            snapshot = self._lifecycle.snapshot if self._lifecycle is not None else None
            if snapshot is not None:
                logger.info(
                    "Prediction attempt cancelled: turn_sequence=%s "
                    "input_revision=%s attempt=%s reason=%s "
                    "request_to_cancel_ms=%s",
                    snapshot.active_turn_sequence,
                    snapshot.input_revision,
                    snapshot.attempt,
                    reason.value,
                    (
                        max(0, self._clock() - snapshot.provider_started_ms)
                        if snapshot.provider_started_ms is not None
                        else None
                    ),
                )
            task.cancel()
            return True
        return False

    def _clear_nowait(self, reason: PredictionInvalidationReason) -> None:
        self._generation += 1
        self._cancel_provider_nowait(reason=reason)
        self._invalidate_current(reason, at_ms=self._clock())
        self._work_event.set()
        worker = self._worker_task
        if worker is not None and not worker.done():
            worker.cancel()
        self._work_event.clear()
        self._lifecycle = None
        self._observation = None
        self._prediction_id = None
        self._input_revision = 0
        self._turn_attempt_count = 0
        self._turn_compatible_extension_count = 0
        self._last_cancelled_attempt_ms = None
        self._snapshot_revision = 0
        self._reset_candidate_consistency()

    def _reset_candidate_consistency(self) -> None:
        self._candidate_counts.clear()
        self._last_ready_input_revision = None

    def _emit(self, snapshot: PredictionSnapshot) -> None:
        sink = self._sink
        if sink is None:
            return
        try:
            sink(snapshot)
        except Exception as exc:
            # A sink exception may originate at a browser boundary. Log only
            # its type so exception text can never echo candidate/user bodies.
            logger.error(
                "Prediction event sink rejected an update: exception_type=%s",
                type(exc).__name__,
            )


def _context_active_matches(
    context_active: PredictionContextTurn,
    active_turn: ActiveConversationTurn,
) -> bool:
    text_matches = (
        context_active.text == active_turn.text
        if not context_active.text_truncated
        else active_turn.text.startswith(context_active.text.removesuffix("…"))
    )
    return bool(
        context_active.turn_id == active_turn.turn_id
        and context_active.turn_sequence == active_turn.turn_sequence
        and context_active.source_utterance_ids == active_turn.source_utterance_ids
        and context_active.source_transcript_sequences
        == active_turn.source_transcript_sequences
        and context_active.audio_source is active_turn.audio_source
        and context_active.speaker_role is active_turn.speaker_role
        and context_active.continuity_quality is active_turn.continuity_quality
        and context_active.original_text_chars == len(active_turn.text)
        and text_matches
    )
