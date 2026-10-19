import asyncio
from uuid import UUID

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import (
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.memory import ConversationMemory, MemoryObservationStatus
from app.services.transcript.models import AudioSource, SpeakerRole
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry
from app.services.transcript.session import SessionConnectionState, TranscriptionSession


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _turn(session_id: UUID, sequence: int, text: str = "remembered body") -> ConversationTurn:
    base = sequence * 100
    return ConversationTurn(
        session_id=session_id,
        turn_id=derive_turn_id(session_id, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=base,
        last_updated_ms=base + 10,
        source_finalized_ms=base + 10,
        finalized_ms=base + 20,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=10,
    )


def _session_with_memory() -> tuple[TranscriptionSession, ConversationMemory]:
    session = TranscriptionSession()
    memory = ConversationMemory(session_id=session.session_id)
    session.attach_conversation_memory(memory)
    return session, memory


def test_logical_session_owns_and_exposes_read_only_memory_snapshot() -> None:
    session, memory = _session_with_memory()
    turn = _turn(session.session_id, 1)

    assert session.conversation_memory is memory
    assert session.observe_memory(turn) is MemoryObservationStatus.COMMITTED
    assert session.memory_snapshot() == memory.snapshot()
    assert session.snapshot().memory == memory.snapshot()


def test_provider_generation_rotation_does_not_change_memory_identity_or_revision() -> None:
    session, memory = _session_with_memory()
    session.observe_memory(_turn(session.session_id, 1))
    before = memory.snapshot()

    session.transition(SessionConnectionState.CONNECTED)
    session.transition(SessionConnectionState.RECONNECTING)
    session.transition(SessionConnectionState.CONNECTED)

    assert session.conversation_memory is memory
    assert memory.snapshot() == before
    assert session.provider_generation == 2


def test_browser_detach_and_resume_reuse_same_logical_memory() -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    session, memory = _session_with_memory()
    session.observe_memory(_turn(session.session_id, 1))
    lease = registry.create(session)

    assert registry.detach(lease)
    resumed = registry.attach(lease.resume_token)

    assert resumed.session is session
    assert resumed.session.conversation_memory is memory
    assert resumed.session.memory_snapshot().stored_turn_count == 1
    assert resumed.session.memory_snapshot().memory_revision == 1


def test_stop_logically_clears_memory_and_rejects_later_observation() -> None:
    session, memory = _session_with_memory()
    session.observe_memory(_turn(session.session_id, 1, "private stop body"))

    session.transition(SessionConnectionState.STOPPED)

    assert memory.snapshot().entries == ()
    assert memory.snapshot().stored_text_chars == 0
    try:
        session.observe_memory(_turn(session.session_id, 2))
    except RuntimeError as exc:
        assert "released" in str(exc)
    else:
        raise AssertionError("stopped memory accepted a new turn")


def test_reset_clears_previous_memory_and_starts_revision_zero_for_new_session() -> None:
    session, memory = _session_with_memory()
    previous_session_id = session.session_id
    session.observe_memory(_turn(previous_session_id, 1, "private reset body"))

    reset = session.reset()

    assert reset.session_id != previous_session_id
    assert reset.memory is not None
    assert reset.memory.session_id == reset.session_id
    assert reset.memory.memory_revision == 0
    assert reset.memory.entries == ()
    assert session.observe_memory(_turn(reset.session_id, 1)) is MemoryObservationStatus.COMMITTED


def test_registry_expiry_stops_session_and_releases_memory() -> None:
    clock = ManualClock()
    registry = InMemoryTranscriptionSessionRegistry(
        resume_ttl_seconds=5,
        clock=clock,
    )
    session, memory = _session_with_memory()
    session.transition(SessionConnectionState.CONNECTED)
    session.observe_memory(_turn(session.session_id, 1, "private expiry body"))
    lease = registry.create(session)
    assert registry.detach(lease)

    clock.value = 6
    assert registry.purge_expired() == 1

    assert session.connection_state is SessionConnectionState.STOPPED
    assert memory.snapshot().entries == ()
    assert registry.size == 0


def test_registry_shutdown_releases_all_session_memory() -> None:
    first, first_memory = _session_with_memory()
    second, second_memory = _session_with_memory()
    first.observe_memory(_turn(first.session_id, 1, "first private body"))
    second.observe_memory(_turn(second.session_id, 1, "second private body"))
    registry = InMemoryTranscriptionSessionRegistry()
    registry.create(first)
    registry.create(second)

    asyncio.run(registry.shutdown())

    assert first_memory.snapshot().entries == ()
    assert second_memory.snapshot().entries == ()
    assert registry.size == 0


def test_session_without_memory_preserves_m4_behavior() -> None:
    session = TranscriptionSession()
    turn = _turn(session.session_id, 1)

    assert session.conversation_memory is None
    assert session.observe_memory(turn) is None
    assert session.memory_snapshot() is None
    assert session.snapshot().memory is None
