import asyncio
from collections.abc import Callable
from uuid import UUID

import pytest

from app.services.transcript.registry import (
    InMemoryTranscriptionSessionRegistry,
    SessionAlreadyAttachedError,
    SessionResumeUnavailableError,
)
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)
from app.services.conversation.models import ContinuityQuality
from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.models import (
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
    AnswerState,
)
from app.services.answer.runtime import AnswerRuntime
from app.services.conversation.identity import (
    derive_assistance_detection_id,
    derive_turn_id,
)
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import AudioSource, CanonicalUtterance, SpeakerRole


LEASE_ONE = UUID("20000000-0000-0000-0000-000000000001")
LEASE_TWO = UUID("20000000-0000-0000-0000-000000000002")


def value_factory(*values: UUID) -> Callable[[], UUID]:
    remaining = iter(values)
    return lambda: next(remaining)


def connected_session() -> TranscriptionSession:
    session = TranscriptionSession()
    session.transition(SessionConnectionState.CONNECTED)
    return session


def test_registry_issues_an_exclusive_opaque_session_lease() -> None:
    registry = InMemoryTranscriptionSessionRegistry(
        token_factory=lambda: "opaque-resume-token",
        lease_id_factory=value_factory(LEASE_ONE),
    )
    session = connected_session()

    lease = registry.create(session)

    assert lease.resume_token == "opaque-resume-token"
    assert lease.lease_id == LEASE_ONE
    assert lease.session is session
    assert registry.size == 1
    with pytest.raises(SessionAlreadyAttachedError):
        registry.attach(lease.resume_token)

    registry.clear()


def test_detach_and_attach_preserve_session_but_replace_connection_lease() -> None:
    registry = InMemoryTranscriptionSessionRegistry(
        token_factory=lambda: "resume-token",
        lease_id_factory=value_factory(LEASE_ONE, LEASE_TWO),
    )
    session = connected_session()
    original = registry.create(session)

    assert registry.detach(original) is True
    resumed = registry.attach(original.resume_token)

    assert resumed.session is session
    assert resumed.resume_token == original.resume_token
    assert resumed.lease_id == LEASE_TWO
    assert registry.detach(original) is False
    assert registry.remove(original) is False
    assert registry.remove(resumed) is True
    assert session.connection_state is SessionConnectionState.STOPPED


def test_expired_detached_session_is_cleaned_up_and_cannot_resume() -> None:
    now = [100.0]
    registry = InMemoryTranscriptionSessionRegistry(
        resume_ttl_seconds=5.0,
        clock=lambda: now[0],
        token_factory=lambda: "expiring-token",
        lease_id_factory=value_factory(LEASE_ONE),
    )
    session = connected_session()
    lease = registry.create(session)
    registry.detach(lease)

    now[0] = 106.0

    with pytest.raises(SessionResumeUnavailableError):
        registry.attach(lease.resume_token)
    assert registry.size == 0
    assert session.connection_state is SessionConnectionState.STOPPED


def test_unknown_resume_token_does_not_reveal_registry_contents() -> None:
    registry = InMemoryTranscriptionSessionRegistry()

    with pytest.raises(
        SessionResumeUnavailableError,
        match="previous transcription session is no longer available",
    ):
        registry.attach("not-a-real-token")


def test_detached_session_is_removed_by_its_expiry_timer() -> None:
    async def scenario() -> None:
        registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=0.01)
        session = connected_session()
        lease = registry.create(session)

        registry.detach(lease)
        await asyncio.sleep(0.03)

        assert session.connection_state is SessionConnectionState.STOPPED
        assert registry.size == 0

    asyncio.run(scenario())


def test_session_expiry_clears_active_conversation_state() -> None:
    clock = [0.0]
    registry = InMemoryTranscriptionSessionRegistry(
        resume_ttl_seconds=5,
        clock=lambda: clock[0],
    )
    session = connected_session()
    lease = registry.create(session)
    partial = CanonicalUtterance(
        session_id=session.session_id,
        utterance_id=UUID("10000000-0000-0000-0000-000000000099"),
        sequence=1,
        revision=1,
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="unfinished",
        is_final=False,
        first_seen_ms=0,
        last_updated_ms=0,
    )
    session.turn_engine.observe(
        partial,
        continuity_quality=ContinuityQuality.NORMAL,
    )
    assert session.conversation_snapshot().active_turn is not None

    registry.detach(lease)
    clock[0] = 5.0
    assert registry.purge_expired() == 1
    assert session.connection_state is SessionConnectionState.STOPPED
    assert session.conversation_snapshot().active_turn is None


def test_session_expiry_cancels_answer_task_without_orphaning_provider() -> None:
    async def scenario() -> None:
        registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=0.01)
        session = connected_session()
        start_gate = asyncio.Event()
        answer_provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderCompleted(sequence=1),),
                    start_gate=start_gate,
                )
            ]
        )
        runtime = AnswerRuntime(
            session_id=session.session_id,
            provider=answer_provider,
            clock=session.elapsed_ms,
            timeout_seconds=0.5,
        )
        session.attach_answer_runtime(runtime)
        turn = ConversationTurn(
            session_id=session.session_id,
            turn_id=derive_turn_id(session.session_id, 1),
            turn_sequence=1,
            source_utterance_ids=(UUID(int=1),),
            source_transcript_sequences=(1,),
            audio_source=AudioSource.MICROPHONE,
            speaker_role=SpeakerRole.LOCAL_USER,
            text="What is Redis?",
            started_ms=0,
            last_updated_ms=0,
            source_finalized_ms=0,
            finalized_ms=0,
            finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
            continuity_quality=ContinuityQuality.NORMAL,
            transcript_final_to_turn_ms=0,
        )
        decision = AssistanceDecision(
            detection_id=derive_assistance_detection_id(turn.turn_id),
            session_id=session.session_id,
            source_turn_id=turn.turn_id,
            source_turn_sequence=1,
            should_assist=True,
            kind=AssistanceKind.QUESTION,
            detected_ms=0,
            turn_to_detection_ms=0,
        )
        runtime.request_answer(decision, turn, recent_finalized_turns=(turn,))
        while len(answer_provider.requests) < 1:
            await asyncio.sleep(0)

        lease = registry.create(session)
        registry.detach(lease)
        await asyncio.sleep(0.03)
        await runtime.wait_idle()

        assert registry.size == 0
        assert session.connection_state is SessionConnectionState.STOPPED
        assert runtime.snapshot().answers[0].state is AnswerState.CANCELLED
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_early_expiry_callback_is_rescheduled(monkeypatch) -> None:
    async def scenario() -> None:
        clock = [0.0]
        registry = InMemoryTranscriptionSessionRegistry(
            resume_ttl_seconds=5.0,
            clock=lambda: clock[0],
        )
        session = connected_session()
        lease = registry.create(session)
        registry.detach(lease)

        scheduled: list[tuple[float, object, tuple[object, ...]]] = []

        class RecordingLoop:
            def call_later(self, delay, callback, *args):
                scheduled.append((delay, callback, args))
                return None

        monkeypatch.setattr(
            "app.services.transcript.registry.asyncio.get_running_loop",
            lambda: RecordingLoop(),
        )
        registry._expire(lease.resume_token, lease.lease_id)

        assert registry.size == 1
        assert len(scheduled) == 1
        assert scheduled[0][0] == 5.0
        assert scheduled[0][2] == (lease.resume_token, lease.lease_id)

        clock[0] = 5.0
        registry._expire(lease.resume_token, lease.lease_id)
        assert registry.size == 0
        assert session.connection_state is SessionConnectionState.STOPPED

    asyncio.run(scenario())


def test_stt_provider_rotation_does_not_cancel_session_owned_answer() -> None:
    async def scenario() -> None:
        session = connected_session()
        completion_gate = asyncio.Event()
        answer_provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderCompleted(sequence=1),),
                    start_gate=completion_gate,
                )
            ]
        )
        runtime = AnswerRuntime(
            session_id=session.session_id,
            provider=answer_provider,
            clock=session.elapsed_ms,
        )
        session.attach_answer_runtime(runtime)
        turn = ConversationTurn(
            session_id=session.session_id,
            turn_id=derive_turn_id(session.session_id, 1),
            turn_sequence=1,
            source_utterance_ids=(UUID(int=1),),
            source_transcript_sequences=(1,),
            audio_source=AudioSource.MICROPHONE,
            speaker_role=SpeakerRole.LOCAL_USER,
            text="What is Redis?",
            started_ms=0,
            last_updated_ms=0,
            source_finalized_ms=0,
            finalized_ms=0,
            finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
            continuity_quality=ContinuityQuality.NORMAL,
            transcript_final_to_turn_ms=0,
        )
        decision = AssistanceDecision(
            detection_id=derive_assistance_detection_id(turn.turn_id),
            session_id=session.session_id,
            source_turn_id=turn.turn_id,
            source_turn_sequence=1,
            should_assist=True,
            kind=AssistanceKind.QUESTION,
            detected_ms=0,
            turn_to_detection_ms=0,
        )
        runtime.request_answer(decision, turn, recent_finalized_turns=(turn,))
        while len(answer_provider.requests) < 1:
            await asyncio.sleep(0)

        session.transition(SessionConnectionState.RECONNECTING)
        session.mark_continuity_degraded()
        session.transition(SessionConnectionState.CONNECTED)

        active = runtime.snapshot()
        assert active.active_answer_id is not None
        assert active.answers[0].state is AnswerState.STARTING
        completion_gate.set()
        await runtime.wait_idle()

        assert runtime.snapshot().answers[0].state is AnswerState.COMPLETED
        assert len(answer_provider.requests) == 1
        session.transition(SessionConnectionState.STOPPED)

    asyncio.run(scenario())


def test_registry_shutdown_awaits_active_answer_cleanup() -> None:
    async def scenario() -> None:
        registry = InMemoryTranscriptionSessionRegistry()
        session = connected_session()
        completion_gate = asyncio.Event()
        answer_provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="partial"),
                        AnswerProviderCompleted(sequence=2),
                    ),
                    step_gates=(None, completion_gate),
                )
            ]
        )
        runtime = AnswerRuntime(
            session_id=session.session_id,
            provider=answer_provider,
            clock=session.elapsed_ms,
        )
        session.attach_answer_runtime(runtime)
        turn = ConversationTurn(
            session_id=session.session_id,
            turn_id=derive_turn_id(session.session_id, 1),
            turn_sequence=1,
            source_utterance_ids=(UUID(int=1),),
            source_transcript_sequences=(1,),
            audio_source=AudioSource.MICROPHONE,
            speaker_role=SpeakerRole.LOCAL_USER,
            text="What is Redis?",
            started_ms=0,
            last_updated_ms=0,
            source_finalized_ms=0,
            finalized_ms=0,
            finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
            continuity_quality=ContinuityQuality.NORMAL,
            transcript_final_to_turn_ms=0,
        )
        decision = AssistanceDecision(
            detection_id=derive_assistance_detection_id(turn.turn_id),
            session_id=session.session_id,
            source_turn_id=turn.turn_id,
            source_turn_sequence=1,
            should_assist=True,
            kind=AssistanceKind.QUESTION,
            detected_ms=0,
            turn_to_detection_ms=0,
        )
        runtime.request_answer(decision, turn, recent_finalized_turns=(turn,))
        while not answer_provider.streams:
            await asyncio.sleep(0)

        registry.create(session)
        await registry.shutdown()

        assert registry.size == 0
        assert session.connection_state is SessionConnectionState.STOPPED
        assert runtime.snapshot().answers[0].state is AnswerState.CANCELLED
        assert runtime.pending_task_count == 0
        assert answer_provider.streams[0].closed

    asyncio.run(scenario())
