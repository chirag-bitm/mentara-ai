import asyncio
import json
import logging
import anyio
from contextlib import suppress
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Callable, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.api.outbound import OutboundBufferFull, OutboundEventWriter
from app.schemas.events import (
    AnswerEventProjector,
    answer_events_from_snapshot,
    conversation_events_from_snapshot,
    ErrorEvent,
    PongEvent,
    question_event_from_decision,
    prediction_event_from_snapshot,
    SessionReadyEvent,
    StatusEvent,
    transcript_event_from_utterance,
    transcript_events_from_snapshot,
    turn_event_from_turn,
)
from app.services.answer.context import (
    BoundedAnswerContextAssembler,
    MemoryAnswerContextAssembler,
)
from app.services.answer.factory import create_answer_provider
from app.services.answer.models import AnswerSnapshot
from app.services.answer.provider import AnswerProviderError
from app.services.answer.runtime import AnswerRuntime
from app.services.conversation.engine import TurnFinalizationPolicy
from app.services.conversation.models import (
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.conversation.runtime import ConversationTurnRuntime
from app.services.memory import (
    ContextPlannerLimits,
    ConversationMemory,
    DeterministicContextPlanner,
    MemoryLimits,
)
from app.services.prediction import (
    DeterministicPredictionContextPlanner,
    DeterministicPredictionTriggerPolicy,
    PredictionContextPlannerLimits,
    PredictionProviderExecutor,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionTriggerPolicyLimits,
    create_prediction_provider,
)
from app.services.prediction.models import (
    PredictionInvalidationReason,
    PredictionSnapshot,
)
from app.services.prediction.provider import PredictionProviderError
from app.services.stt.base import (
    STTProvider,
    STTProviderConfigurationError,
    STTProviderError,
)
from app.services.stt.factory import create_resilient_stt_provider
from app.services.stt.rotation import (
    ProviderLifecycleEvent,
    ProviderLifecycleEventKind,
)
from app.services.transcript.registry import (
    InMemoryTranscriptionSessionRegistry,
    SessionAlreadyAttachedError,
    SessionResumeUnavailableError,
    TranscriptionSessionLease,
)
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)

router = APIRouter(tags=["websocket"])
logger = logging.getLogger(__name__)

SESSION_COMMAND_TIMEOUT_SECONDS = 5.0
transcription_session_registry = InMemoryTranscriptionSessionRegistry(
    resume_ttl_seconds=30.0
)


@dataclass(slots=True, frozen=True)
class _SessionRequest:
    resume_token: str | None


async def send_event(websocket: WebSocket, event: object) -> None:
    await websocket.send_json(  # type: ignore[attr-defined]
        event.model_dump(mode="json", exclude_none=True)
    )


@router.websocket("/ws/health")
async def websocket_health(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        message = await websocket.receive_text()
        if message.lower() == "ping":
            await send_event(websocket, PongEvent())
        else:
            await send_event(
                websocket,
                ErrorEvent(code="INVALID_MESSAGE", message="Send the text 'ping'."),
            )
    except WebSocketDisconnect:
        return
    finally:
        with suppress(RuntimeError):
            await websocket.close()


async def receive_session_request(websocket: WebSocket) -> _SessionRequest:
    try:
        raw_command = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=SESSION_COMMAND_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise ValueError("Session handshake timed out.") from exc

    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError as exc:
        raise ValueError("The first message must be a session command.") from exc

    if not isinstance(command, dict):
        raise ValueError("The first message must be a session command.")

    command_type = command.get("type")
    if command_type == "session.start":
        return _SessionRequest(resume_token=None)
    if command_type == "session.resume":
        resume_token = command.get("resume_token")
        if (
            isinstance(resume_token, str)
            and resume_token.strip()
            and len(resume_token) <= 256
        ):
            return _SessionRequest(resume_token=resume_token)
        raise ValueError("A valid resume token is required.")
    raise ValueError("Send 'session.start' or 'session.resume' first.")


async def browser_to_provider(
    websocket: WebSocket,
    provider: STTProvider,
    publish_event: Callable[[object], None],
) -> Literal["stop", "disconnect"]:
    while True:
        message = await websocket.receive()
        message_type = message.get("type")

        if message_type == "websocket.disconnect":
            return "disconnect"

        audio = message.get("bytes")
        if audio:
            await provider.send_audio(audio)
            continue

        text = message.get("text")
        if not text:
            continue

        try:
            command = json.loads(text)
        except json.JSONDecodeError:
            continue

        if not isinstance(command, dict):
            continue

        if command.get("type") == "stop":
            publish_event(
                StatusEvent(status="stopping", message="Finalizing the transcript…"),
            )
            await provider.finish()
            return "stop"


async def provider_to_browser(
    provider: STTProvider,
    session: TranscriptionSession,
    publish_event: Callable[[object], None],
    analysis_runtime: ConversationTurnRuntime | None = None,
) -> None:
    async for result in provider.results():
        utterance = session.apply(result)
        if utterance is not None:
            publish_event(transcript_event_from_utterance(utterance))
            if analysis_runtime is not None:
                update = await analysis_runtime.observe(
                    utterance,
                    continuity_quality=session.conversation_continuity_quality,
                )
                prediction_runtime = session.prediction_runtime
                if prediction_runtime is not None and update.active_turn is not None:
                    memory_snapshot = session.memory_snapshot()
                    try:
                        prediction_runtime.observe_nowait(
                            update.active_turn,
                            utterance,
                            memory_revision=(
                                memory_snapshot.memory_revision
                                if memory_snapshot is not None
                                else 0
                            ),
                        )
                    except Exception as exc:
                        logger.error(
                            "Prediction observation rejected: exception_type=%s",
                            type(exc).__name__,
                        )
                session.acknowledge_conversation_utterance(utterance)


async def handle_provider_lifecycle(
    session: TranscriptionSession,
    event: ProviderLifecycleEvent,
    publish_event: Callable[[object], None],
) -> None:
    status_value: Literal["ready", "reconnecting", "degraded"]
    if event.kind is ProviderLifecycleEventKind.DEGRADED:
        session.mark_continuity_degraded()
        if session.connection_state is not SessionConnectionState.DEGRADED:
            session.transition(SessionConnectionState.DEGRADED)
        status_value = "degraded"
    elif event.kind is ProviderLifecycleEventKind.RECONNECTING:
        if session.connection_state is not SessionConnectionState.RECONNECTING:
            session.transition(SessionConnectionState.RECONNECTING)
        status_value = "reconnecting"
    else:
        if session.connection_state is not SessionConnectionState.CONNECTED:
            session.transition(SessionConnectionState.CONNECTED)
        status_value = "ready"

    publish_event(StatusEvent(status=status_value, message=event.message))


async def _send_session_error(
    websocket: WebSocket,
    writer: OutboundEventWriter,
    *,
    code: str,
    message: str,
    close_code: int,
) -> None:
    writer.publish(ErrorEvent(code=code, message=message))
    with suppress(TimeoutError, RuntimeError):
        await writer.drain()
    await websocket.close(code=close_code)


def _mark_browser_disconnected(session: TranscriptionSession) -> None:
    session.mark_continuity_degraded()
    if session.connection_state in {
        SessionConnectionState.CONNECTED,
        SessionConnectionState.DEGRADED,
    }:
        session.transition(SessionConnectionState.RECONNECTING)


@router.websocket("/ws/transcribe")
async def transcribe(websocket: WebSocket) -> None:
    settings = get_settings()
    origin = websocket.headers.get("origin")

    if origin and origin != settings.frontend_origin:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    writer = OutboundEventWriter(
        websocket,
        max_items=settings.answer_outbound_buffer_items,
        max_coalesced_delta_chars=settings.answer_delta_max_coalesced_chars,
    )
    writer_task = writer.start()
    outbound_overflowed = False

    def publish_event(event: object) -> None:
        nonlocal outbound_overflowed
        try:
            writer.publish(event)  # type: ignore[arg-type]
        except OutboundBufferFull:
            if not outbound_overflowed:
                logger.warning("Browser outbound buffer reached its bounded limit.")
            outbound_overflowed = True
        except RuntimeError:
            pass

    if not settings.stt_configured:
        publish_event(
            ErrorEvent(
                code="STT_NOT_CONFIGURED",
                message=(
                    "GEMINI_API_KEY is missing in backend/.env."
                    if settings.stt_provider == "gemini"
                    else f"The '{settings.stt_provider}' STT provider is not configured."
                ),
            ),
        )
        with suppress(TimeoutError, RuntimeError):
            await writer.drain()
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        await writer.close()
        return

    publish_event(
        StatusEvent(status="connecting", message="Connecting to streaming STT…"),
    )

    try:
        session_request = await receive_session_request(websocket)
    except ValueError as exc:
        await _send_session_error(
            websocket,
            writer,
            code="INVALID_SESSION_COMMAND",
            message=str(exc),
            close_code=status.WS_1008_POLICY_VIOLATION,
        )
        await writer.close()
        return
    except WebSocketDisconnect:
        await writer.close()
        return

    lease: TranscriptionSessionLease | None = None
    resumed = session_request.resume_token is not None
    if resumed:
        try:
            lease = transcription_session_registry.attach(
                session_request.resume_token or ""
            )
        except SessionResumeUnavailableError as exc:
            await _send_session_error(
                websocket,
                writer,
                code="SESSION_RESUME_UNAVAILABLE",
                message=str(exc),
                close_code=4404,
            )
            await writer.close()
            return
        except SessionAlreadyAttachedError as exc:
            await _send_session_error(
                websocket,
                writer,
                code="SESSION_ALREADY_ATTACHED",
                message=str(exc),
                close_code=4409,
            )
            await writer.close()
            return
        session = lease.session
        publish_event(
            StatusEvent(
                status="reconnecting",
                message="Reattaching to the previous transcription session…",
            ),
        )
    else:
        session = TranscriptionSession(
            turn_policy=TurnFinalizationPolicy(
                merge_window_ms=settings.conversation_turn_merge_window_ms
            )
        )
        if settings.memory_context_enabled:
            session.attach_conversation_memory(
                ConversationMemory(
                    session_id=session.session_id,
                    limits=MemoryLimits(
                        max_retained_turns=settings.memory_max_retained_turns,
                        max_retained_text_chars=(
                            settings.memory_max_retained_text_chars
                        ),
                        max_entry_text_chars=settings.memory_max_turn_chars,
                    ),
                )
            )
        if settings.answer_generation_enabled:
            try:
                answer_provider = create_answer_provider(settings)
            except AnswerProviderError as exc:
                logger.warning(
                    "Answer generation unavailable: category=%s",
                    exc.category.value,
                )
            else:
                m4_context_assembler = BoundedAnswerContextAssembler(
                    max_recent_turns=settings.answer_context_recent_turns,
                    max_total_chars=settings.answer_context_max_total_chars,
                    max_turn_chars=settings.answer_context_max_turn_chars,
                )
                context_assembler = m4_context_assembler
                if session.conversation_memory is not None:
                    context_assembler = MemoryAnswerContextAssembler(
                        snapshot_provider=session.memory_snapshot,
                        planner=DeterministicContextPlanner(
                            limits=ContextPlannerLimits(
                                max_recent_turns=(
                                    settings.memory_context_recent_turns
                                ),
                                max_relevant_older_turns=(
                                    settings.memory_context_relevant_turns
                                ),
                                max_total_text_chars=(
                                    settings.answer_context_max_total_chars
                                ),
                                max_turn_text_chars=(
                                    settings.answer_context_max_turn_chars
                                ),
                            )
                        ),
                        fallback=m4_context_assembler,
                    )
                session.attach_answer_runtime(
                    AnswerRuntime(
                        session_id=session.session_id,
                        provider=answer_provider,
                        clock=session.elapsed_ms,
                        context_assembler=context_assembler,
                        timeout_seconds=settings.answer_generation_timeout_seconds,
                    )
                )
        if settings.prediction_enabled:
            try:
                prediction_provider = create_prediction_provider(settings)
            except PredictionProviderError as exc:
                logger.warning(
                    "Prediction unavailable: category=%s",
                    exc.category.value,
                )
            else:
                prediction_executor = PredictionProviderExecutor(
                    provider=prediction_provider,
                    clock=session.elapsed_ms,
                    max_candidates=settings.prediction_max_candidates,
                    max_output_tokens=settings.prediction_max_output_tokens,
                )
                session.attach_prediction_runtime(
                    PredictionRuntime(
                        session_id=session.session_id,
                        executor=prediction_executor,
                        clock=session.elapsed_ms,
                        limits=PredictionRuntimeLimits(
                            coalesce_seconds=(
                                settings.prediction_coalesce_ms / 1_000
                            ),
                            provider_timeout_seconds=(
                                settings.prediction_provider_timeout_seconds
                            ),
                            max_attempts_per_turn=(
                                settings.prediction_max_attempts_per_turn
                            ),
                            max_calls_per_session=(
                                settings.prediction_max_calls_per_session
                            ),
                            cancelled_attempt_cooldown_seconds=(
                                settings.prediction_cancelled_attempt_cooldown_ms
                                / 1_000
                            ),
                            max_compatible_extension_chars=(
                                settings.prediction_max_compatible_extension_chars
                            ),
                        ),
                        trigger_policy=DeterministicPredictionTriggerPolicy(
                            limits=PredictionTriggerPolicyLimits(
                                min_active_chars=(
                                    settings.prediction_min_active_chars
                                ),
                                min_lexical_tokens=(
                                    settings.prediction_min_lexical_tokens
                                ),
                                long_partial_chars=(
                                    settings.prediction_long_partial_chars
                                ),
                                min_call_interval_ms=(
                                    settings.prediction_min_call_interval_ms
                                ),
                            )
                        ),
                        context_planner=DeterministicPredictionContextPlanner(
                            limits=PredictionContextPlannerLimits(
                                max_recent_turns=(
                                    settings.prediction_context_recent_turns
                                ),
                                max_relevant_older_turns=(
                                    settings.prediction_context_relevant_turns
                                ),
                                max_total_text_chars=(
                                    settings.prediction_context_max_total_chars
                                ),
                                max_active_turn_chars=(
                                    settings.prediction_context_max_active_chars
                                ),
                                max_memory_turn_chars=(
                                    settings.prediction_context_max_memory_turn_chars
                                ),
                            )
                        ),
                        memory_snapshot_supplier=session.memory_snapshot,
                    )
                )

    async def lifecycle_callback(event: ProviderLifecycleEvent) -> None:
        await handle_provider_lifecycle(session, event, publish_event)

    provider: STTProvider | None = None
    analysis_runtime: ConversationTurnRuntime | None = None
    answer_runtime = session.answer_runtime
    prediction_runtime = session.prediction_runtime
    answer_sink_id: UUID | None = None
    prediction_sink_id: UUID | None = None
    answer_projector = AnswerEventProjector()
    browser_task: asyncio.Task[Literal["stop", "disconnect"]] | None = None
    provider_task: asyncio.Task[None] | None = None
    analysis_flushed = False
    disconnected = False
    completed = False

    try:
        provider = create_resilient_stt_provider(
            settings,
            lifecycle_callback=lifecycle_callback,
        )
        await provider.connect()
        session.transition(SessionConnectionState.CONNECTED)

        if lease is None:
            lease = transcription_session_registry.create(session)

        publish_event(
            SessionReadyEvent(
                session_id=session.session_id,
                resume_token=lease.resume_token,
                resumed=resumed,
                resume_ttl_seconds=lease.resume_ttl_seconds,
            ),
        )

        if resumed:
            session.mark_continuity_degraded()
            publish_event(
                StatusEvent(
                    status="degraded",
                    message=(
                        "Session restored. Speech during the browser reconnect may "
                        "be incomplete."
                    ),
                ),
            )
            for event in transcript_events_from_snapshot(
                session.snapshot().transcript
            ):
                publish_event(event)
                if writer.buffered_count >= settings.answer_outbound_buffer_items // 2:
                    await writer.drain()
            if settings.conversation_analysis_enabled:
                for event in conversation_events_from_snapshot(
                    session.conversation_snapshot()
                ):
                    publish_event(event)
                    if (
                        writer.buffered_count
                        >= settings.answer_outbound_buffer_items // 2
                    ):
                        await writer.drain()

        if answer_runtime is not None:
            answer_snapshot = answer_runtime.snapshot()
            for event, snapshot in zip(
                answer_events_from_snapshot(answer_snapshot),
                answer_snapshot.answers,
                strict=True,
            ):
                publish_event(event)
                answer_projector.seed(snapshot)
                if writer.buffered_count >= settings.answer_outbound_buffer_items // 2:
                    await writer.drain()
            answer_sink_id = uuid4()

            def on_answer_snapshot(snapshot: AnswerSnapshot) -> None:
                event = answer_projector.project(snapshot)
                if event is not None:
                    publish_event(event)

            answer_runtime.attach_sink(answer_sink_id, on_answer_snapshot)

        if prediction_runtime is not None:
            prediction_runtime.attach_browser()
            prediction_sink_id = uuid4()

            def on_prediction_snapshot(snapshot: PredictionSnapshot) -> None:
                publish_event(prediction_event_from_snapshot(snapshot))

            prediction_runtime.attach_sink(
                prediction_sink_id,
                on_prediction_snapshot,
            )

        publish_event(
            StatusEvent(
                status="ready",
                message=(
                    "Previous transcription session restored."
                    if resumed
                    else "Streaming STT is ready."
                ),
            ),
        )

        if settings.conversation_analysis_enabled:
            async def on_turn_finalized(turn: ConversationTurn) -> None:
                if prediction_runtime is not None:
                    prediction_session = prediction_runtime.snapshot()
                    current_prediction = prediction_session.current
                    if (
                        current_prediction is not None
                        and current_prediction.active_turn_id == turn.turn_id
                    ):
                        logger.info(
                            "Prediction turn outcome: turn_sequence=%s "
                            "state=%s attempt_count=%s "
                            "compatible_extension_count=%s "
                            "prediction_ready_before_turn_final_ms=%s "
                            "session_attempt_count=%s cancelled_call_count=%s "
                            "stale_discard_count=%s",
                            turn.turn_sequence,
                            current_prediction.state.value,
                            prediction_runtime.turn_attempt_count,
                            prediction_runtime.turn_compatible_extension_count,
                            (
                                turn.finalized_ms - current_prediction.ready_ms
                                if current_prediction.ready_ms is not None
                                else None
                            ),
                            prediction_session.provider_attempt_count,
                            prediction_session.cancelled_call_count,
                            prediction_session.stale_discard_count,
                        )
                    prediction_runtime.invalidate_turn_nowait(
                        turn.turn_id,
                        reason=PredictionInvalidationReason.TURN_FINALIZED,
                        at_ms=turn.finalized_ms,
                    )
                memory_started_ns = perf_counter_ns()
                try:
                    memory_status = session.observe_memory(turn)
                except (ValueError, RuntimeError) as exc:
                    logger.error(
                        "Conversation memory observation rejected: "
                        "turn_sequence=%s exception_type=%s memory_observe_ms=%s",
                        turn.turn_sequence,
                        type(exc).__name__,
                        round((perf_counter_ns() - memory_started_ns) / 1_000_000, 3),
                    )
                else:
                    memory_snapshot = session.memory_snapshot()
                    if memory_status is not None and memory_snapshot is not None:
                        logger.info(
                            "Conversation memory observed: turn_sequence=%s "
                            "observation_status=%s memory_observe_ms=%s "
                            "memory_revision=%s stored_turn_count=%s "
                            "stored_text_chars=%s",
                            turn.turn_sequence,
                            memory_status.value,
                            round(
                                (perf_counter_ns() - memory_started_ns) / 1_000_000,
                                3,
                            ),
                            memory_snapshot.memory_revision,
                            memory_snapshot.stored_turn_count,
                            memory_snapshot.stored_text_chars,
                        )
                detected_ms = session.elapsed_ms()
                decision = session.detect_assistance(
                    turn,
                    detected_ms=max(detected_ms, turn.finalized_ms),
                )
                publish_event(turn_event_from_turn(turn))
                if decision is not None and decision.should_assist:
                    publish_event(question_event_from_decision(decision))
                    if answer_runtime is not None:
                        submission = answer_runtime.request_answer(
                            decision,
                            turn,
                            recent_finalized_turns=(
                                session.conversation_snapshot().finalized_turns
                            ),
                        )
                        if submission.created:
                            logger.info(
                                "Answer request created: turn_sequence=%s "
                                "question_detected_to_answer_request_ms=%s",
                                turn.turn_sequence,
                                submission.snapshot.question_detected_to_answer_request_ms,
                            )
                logger.info(
                    "Conversation analysis completed: turn_sequence=%s "
                    "transcript_final_to_turn_ms=%s turn_to_detection_ms=%s "
                    "should_assist=%s",
                    turn.turn_sequence,
                    turn.transcript_final_to_turn_ms,
                    decision.turn_to_detection_ms if decision is not None else 0,
                    decision.should_assist if decision is not None else False,
                )

            analysis_runtime = ConversationTurnRuntime(
                engine=session.turn_engine,
                clock=session.elapsed_ms,
                on_turn_finalized=on_turn_finalized,
            )
            await analysis_runtime.resume()

        browser_task = asyncio.create_task(
            browser_to_provider(websocket, provider, publish_event)
        )
        provider_task = asyncio.create_task(
            provider_to_browser(
                provider,
                session,
                publish_event,
                analysis_runtime,
            )
        )

        done, _ = await asyncio.wait(
            {browser_task, provider_task, writer_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if writer_task in done:
            disconnected = lease is not None
            browser_task.cancel()
            provider_task.cancel()
        elif browser_task in done:
            reason = browser_task.result()
            if reason == "stop":
                try:
                    await asyncio.wait_for(provider_task, timeout=5)
                except TimeoutError:
                    provider_task.cancel()
                if analysis_runtime is not None:
                    await analysis_runtime.flush(
                        reason=TurnFinalizationReason.STOP_REQUESTED
                    )
                    analysis_flushed = True
                if answer_runtime is not None:
                    answer_runtime.cancel_active()
                completed = True
            else:
                disconnected = True
                provider_task.cancel()
        else:
            provider_task.result()
            browser_task.cancel()
            if analysis_runtime is not None:
                session.mark_continuity_degraded()
                await analysis_runtime.flush(
                    reason=TurnFinalizationReason.PROVIDER_FAILED
                )
                analysis_flushed = True
            if answer_runtime is not None:
                answer_runtime.cancel_active()
            completed = True

        for task in (browser_task, provider_task):
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, WebSocketDisconnect):
                await task

        if completed and websocket.client_state.name == "CONNECTED":
            publish_event(
                StatusEvent(status="stopped", message="Transcription stopped."),
            )
            with suppress(TimeoutError, RuntimeError):
                await writer.drain()
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)

    except STTProviderConfigurationError as exc:
        logger.warning("Streaming STT provider is not configured.")
        with suppress(RuntimeError, WebSocketDisconnect):
            await _send_session_error(
                websocket,
                writer,
                code="STT_NOT_CONFIGURED",
                message=str(exc),
                close_code=status.WS_1011_INTERNAL_ERROR,
            )
    except WebSocketDisconnect:
        disconnected = lease is not None
        logger.info("Browser disconnected; logical session retained temporarily.")
    except asyncio.CancelledError:
        disconnected = lease is not None
        logger.info("Browser lease cancelled; logical session retained temporarily.")
    except (STTProviderError, OSError, TimeoutError) as exc:
        if analysis_runtime is not None:
            session.mark_continuity_degraded()
            with suppress(RuntimeError, WebSocketDisconnect):
                await analysis_runtime.flush(
                    reason=TurnFinalizationReason.PROVIDER_FAILED
                )
            analysis_flushed = True
        session.transition(SessionConnectionState.ERROR)
        logger.exception("Streaming transcription failed")
        with suppress(RuntimeError, WebSocketDisconnect):
            publish_event(ErrorEvent(code="STT_CONNECTION_ERROR", message=str(exc)))
            with suppress(TimeoutError, RuntimeError):
                await writer.drain()
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
    except Exception:
        if analysis_runtime is not None:
            await analysis_runtime.cancel()
        session.transition(SessionConnectionState.ERROR)
        logger.exception("Unexpected transcription error")
        with suppress(RuntimeError, WebSocketDisconnect):
            publish_event(
                ErrorEvent(code="INTERNAL_ERROR", message="Unexpected backend error.")
            )
            with suppress(TimeoutError, RuntimeError):
                await writer.drain()
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        raise
    finally:
        with anyio.CancelScope(shield=True):
            peer_tasks = tuple(
                task for task in (browser_task, provider_task) if task is not None
            )
            for task in peer_tasks:
                if not task.done():
                    task.cancel()
            if peer_tasks:
                await asyncio.gather(*peer_tasks, return_exceptions=True)

            if analysis_runtime is not None:
                if disconnected:
                    await analysis_runtime.pause()
                elif analysis_flushed:
                    await analysis_runtime.pause()
                else:
                    await analysis_runtime.cancel()
            if answer_runtime is not None and answer_sink_id is not None:
                answer_runtime.detach_sink(answer_sink_id)
            if prediction_runtime is not None and prediction_sink_id is not None:
                prediction_runtime.detach_sink(prediction_sink_id)
            if disconnected and prediction_runtime is not None:
                await prediction_runtime.disconnect()
            if provider is not None:
                await provider.close()

            if lease is None:
                if session.connection_state is not SessionConnectionState.STOPPED:
                    session.transition(SessionConnectionState.STOPPED)
            elif disconnected:
                _mark_browser_disconnected(session)
                transcription_session_registry.detach(lease)
            else:
                if session.connection_state is not SessionConnectionState.STOPPED:
                    session.transition(SessionConnectionState.STOPPED)
                transcription_session_registry.remove(lease)
            if not disconnected and answer_runtime is not None:
                await answer_runtime.wait_idle()
            if not disconnected and prediction_runtime is not None:
                await prediction_runtime.wait_idle()
            await writer.close()
