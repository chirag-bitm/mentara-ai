import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

import pytest

from app.api.websocket import handle_provider_lifecycle, provider_to_browser
from app.services.conversation.models import ContinuityQuality
from app.services.conversation.runtime import ConversationTurnRuntime
from app.services.memory import ConversationMemory
from app.services.prediction import (
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionInvalidationReason,
    PredictionProviderResult,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionState,
)
from app.services.prediction.runtime import PredictionAttemptInput
from app.services.stt.base import TranscriptResult
from app.services.stt.rotation import (
    ProviderLifecycleEvent,
    ProviderLifecycleEventKind,
)
from app.services.transcript.aggregator import TranscriptAggregator
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)


SESSION_ID = UUID("00000000-0000-0000-0000-000000000011")
OTHER_SESSION_ID = UUID("00000000-0000-0000-0000-000000000012")
UTTERANCE_ID = UUID("10000000-0000-0000-0000-000000000011")


class ImmediateExecutor:
    def __init__(self) -> None:
        self.attempts: list[PredictionAttemptInput] = []

    async def execute(
        self,
        attempt: PredictionAttemptInput,
    ) -> PredictionProviderResult:
        self.attempts.append(attempt)
        return PredictionProviderResult(
            candidates=(
                PredictionCandidate(
                    PredictionCandidateKind.QUESTION,
                    "Why did you choose Redis?",
                    ("redis",),
                ),
            )
        )


class BlockingExecutor(ImmediateExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def execute(
        self,
        attempt: PredictionAttemptInput,
    ) -> PredictionProviderResult:
        self.attempts.append(attempt)
        self.started.set()
        await self.gate.wait()
        return PredictionProviderResult(candidates=())


@dataclass(slots=True)
class IncrementingClock:
    value: int = 0

    def __call__(self) -> int:
        self.value += 1
        return self.value


class ResultProvider:
    async def connect(self) -> None:
        return None

    async def send_audio(self, _audio: bytes) -> None:
        return None

    async def finish(self) -> None:
        return None

    async def results(self) -> AsyncIterator[TranscriptResult]:
        yield TranscriptResult(
            text="You mentioned Redis",
            is_final=True,
            speech_final=True,
        )
        yield TranscriptResult(
            text="You mentioned Redis",
            is_final=False,
            speech_final=False,
        )

    async def close(self) -> None:
        return None


def make_session() -> TranscriptionSession:
    return TranscriptionSession(
        aggregator=TranscriptAggregator(
            session_id=SESSION_ID,
            clock=IncrementingClock(),
            session_id_factory=lambda: OTHER_SESSION_ID,
            utterance_id_factory=lambda: UTTERANCE_ID,
        )
    )


def make_runtime(session: TranscriptionSession, executor) -> PredictionRuntime:
    return PredictionRuntime(
        session_id=session.session_id,
        executor=executor,
        clock=session.elapsed_ms,
        limits=PredictionRuntimeLimits(
            coalesce_seconds=0,
            provider_timeout_seconds=1,
            max_attempts_per_turn=2,
            max_calls_per_session=4,
        ),
    )


def test_session_owns_prediction_runtime_and_rejects_cross_session_attachment() -> None:
    session = make_session()
    executor = ImmediateExecutor()
    attached = make_runtime(session, executor)
    session.attach_prediction_runtime(attached)

    assert session.prediction_runtime is attached
    assert session.snapshot().prediction is not None
    session.attach_prediction_runtime(attached)

    other = PredictionRuntime(
        session_id=OTHER_SESSION_ID,
        executor=executor,
        clock=lambda: 0,
        limits=PredictionRuntimeLimits(0, 1, 1, 1),
    )
    with pytest.raises(ValueError, match="logical session"):
        session.attach_prediction_runtime(other)


def test_canonical_m3_active_turn_is_observed_without_mutating_memory() -> None:
    async def scenario() -> None:
        session = make_session()
        memory = ConversationMemory(session_id=session.session_id)
        session.attach_conversation_memory(memory)
        executor = ImmediateExecutor()
        prediction = make_runtime(session, executor)
        session.attach_prediction_runtime(prediction)
        analysis = ConversationTurnRuntime(
            engine=session.turn_engine,
            clock=session.elapsed_ms,
        )
        before = memory.snapshot()
        published = []

        await provider_to_browser(
            ResultProvider(),
            session,
            published.append,
            analysis,
        )
        await prediction.wait_idle()

        after = memory.snapshot()
        assert len(executor.attempts) == 1
        assert executor.attempts[0].active_turn.text == "You mentioned Redis"
        assert executor.attempts[0].triggering_utterance.utterance_id == UTTERANCE_ID
        assert after == before
        assert session.conversation_snapshot().finalized_turns == ()
        assert prediction.snapshot().state is PredictionState.READY
        await analysis.cancel()
        prediction.shutdown_nowait()
        await prediction.wait_idle()

    asyncio.run(scenario())


def test_stop_and_reset_clear_prediction_without_changing_other_session_domains() -> None:
    async def scenario() -> None:
        session = make_session()
        executor = BlockingExecutor()
        prediction = make_runtime(session, executor)
        events = []
        prediction.attach_sink(UUID(int=81), events.append)
        session.attach_prediction_runtime(prediction)
        update = session.turn_engine.observe(
            session.apply(
                TranscriptResult("You mentioned Redis", False, False)
            ),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        assert update.active_turn is not None
        canonical = session.snapshot().transcript.active_utterance
        assert canonical is not None
        prediction.observe_nowait(update.active_turn, canonical, memory_revision=0)
        await executor.started.wait()

        session.transition(SessionConnectionState.STOPPED)
        await prediction.wait_idle()
        assert prediction.snapshot().state is PredictionState.IDLE
        assert prediction.pending_task_count == 0
        assert any(
            event.invalidation_reason is PredictionInvalidationReason.STOP_REQUESTED
            for event in events
            if event.state is PredictionState.INVALIDATED
        )

        fresh = make_session()
        fresh_prediction = make_runtime(fresh, ImmediateExecutor())
        fresh.attach_prediction_runtime(fresh_prediction)
        reset = fresh.reset()
        assert reset.session_id == OTHER_SESSION_ID
        assert fresh_prediction.session_id == OTHER_SESSION_ID
        assert reset.prediction is not None
        assert reset.prediction.state is PredictionState.IDLE

    asyncio.run(scenario())


def test_registry_expiry_and_shutdown_cancel_prediction_with_exact_reason() -> None:
    async def scenario() -> None:
        clock = [0.0]
        registry = InMemoryTranscriptionSessionRegistry(
            resume_ttl_seconds=1,
            clock=lambda: clock[0],
            token_factory=lambda: "prediction-resume",
        )
        session = make_session()
        executor = BlockingExecutor()
        prediction = make_runtime(session, executor)
        events = []
        prediction.attach_sink(UUID(int=82), events.append)
        session.attach_prediction_runtime(prediction)
        update = session.turn_engine.observe(
            session.apply(TranscriptResult("You mentioned Redis", False, False)),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        canonical = session.snapshot().transcript.active_utterance
        assert update.active_turn is not None and canonical is not None
        prediction.observe_nowait(update.active_turn, canonical, memory_revision=0)
        await executor.started.wait()

        lease = registry.create(session)
        assert registry.detach(lease) is True
        clock[0] = 2
        assert registry.purge_expired() == 1
        await prediction.wait_idle()
        assert registry.size == 0
        assert prediction.pending_task_count == 0
        assert any(
            event.invalidation_reason is PredictionInvalidationReason.SESSION_EXPIRED
            for event in events
            if event.state is PredictionState.INVALIDATED
        )

        shutdown_registry = InMemoryTranscriptionSessionRegistry(
            token_factory=lambda: "shutdown-resume"
        )
        shutdown_session = make_session()
        shutdown_executor = BlockingExecutor()
        shutdown_prediction = make_runtime(shutdown_session, shutdown_executor)
        shutdown_events = []
        shutdown_prediction.attach_sink(UUID(int=83), shutdown_events.append)
        shutdown_session.attach_prediction_runtime(shutdown_prediction)
        update = shutdown_session.turn_engine.observe(
            shutdown_session.apply(
                TranscriptResult("You mentioned Redis", False, False)
            ),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        canonical = shutdown_session.snapshot().transcript.active_utterance
        assert update.active_turn is not None and canonical is not None
        shutdown_prediction.observe_nowait(
            update.active_turn,
            canonical,
            memory_revision=0,
        )
        await shutdown_executor.started.wait()
        shutdown_registry.create(shutdown_session)

        await shutdown_registry.shutdown()
        assert shutdown_prediction.pending_task_count == 0
        assert any(
            event.invalidation_reason
            is PredictionInvalidationReason.BACKEND_SHUTDOWN
            for event in shutdown_events
            if event.state is PredictionState.INVALIDATED
        )

    asyncio.run(scenario())


def test_stt_rotation_degradation_invalidates_without_duplicate_identity_or_call() -> None:
    async def scenario() -> None:
        session = make_session()
        session.transition(SessionConnectionState.CONNECTED)
        executor = ImmediateExecutor()
        prediction = make_runtime(session, executor)
        session.attach_prediction_runtime(prediction)
        canonical = session.apply(
            TranscriptResult("You mentioned Redis", False, False)
        )
        assert canonical is not None
        update = session.turn_engine.observe(
            canonical,
            continuity_quality=ContinuityQuality.NORMAL,
        )
        assert update.active_turn is not None
        prediction.observe_nowait(update.active_turn, canonical, memory_revision=0)
        await prediction.wait_idle()
        before = prediction.snapshot().current
        assert before is not None

        statuses = []
        await handle_provider_lifecycle(
            session,
            ProviderLifecycleEvent(
                kind=ProviderLifecycleEventKind.DEGRADED,
                generation=1,
                reason="forced_rotation",
                message="Recent words may be incomplete.",
            ),
            statuses.append,
        )

        after = prediction.snapshot().current
        assert after is not None
        assert after.prediction_id == before.prediction_id
        assert after.state is PredictionState.INVALIDATED
        assert after.invalidation_reason is (
            PredictionInvalidationReason.CONTINUITY_DEGRADED
        )
        assert len(executor.attempts) == 1
        assert session.connection_state is SessionConnectionState.DEGRADED
        prediction.shutdown_nowait()
        await prediction.wait_idle()

    asyncio.run(scenario())
