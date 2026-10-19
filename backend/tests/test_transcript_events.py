from dataclasses import replace
from uuid import UUID

from app.schemas.events import (
    SessionReadyEvent,
    StatusEvent,
    transcript_event_from_utterance,
    transcript_events_from_snapshot,
)
from app.services.transcript.models import (
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
    TranscriptSessionSnapshot,
)


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
UTTERANCE_ID = UUID("10000000-0000-0000-0000-000000000001")
UTTERANCE_ID_TWO = UUID("10000000-0000-0000-0000-000000000002")


def utterance(*, is_final: bool) -> CanonicalUtterance:
    return CanonicalUtterance(
        session_id=SESSION_ID,
        utterance_id=UTTERANCE_ID,
        sequence=2 if is_final else 1,
        revision=2 if is_final else 1,
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="Can you explain Redis?" if is_final else "Can you explain Redis",
        is_final=is_final,
        first_seen_ms=10,
        last_updated_ms=40 if is_final else 20,
        finalized_ms=40 if is_final else None,
        confidence=0.91 if is_final else None,
    )


def test_partial_event_serializes_canonical_fields_without_unknown_values() -> None:
    event = transcript_event_from_utterance(utterance(is_final=False))

    assert event.model_dump(mode="json", exclude_none=True) == {
        "session_id": str(SESSION_ID),
        "utterance_id": str(UTTERANCE_ID),
        "sequence": 1,
        "revision": 1,
        "audio_source": "microphone",
        "speaker_role": "local_user",
        "text": "Can you explain Redis",
        "first_seen_ms": 10,
        "last_updated_ms": 20,
        "type": "transcript.partial",
        "is_final": False,
    }


def test_final_event_serializes_finalization_and_provider_confidence() -> None:
    event = transcript_event_from_utterance(utterance(is_final=True))

    assert event.model_dump(mode="json", exclude_none=True) == {
        "session_id": str(SESSION_ID),
        "utterance_id": str(UTTERANCE_ID),
        "sequence": 2,
        "revision": 2,
        "audio_source": "microphone",
        "speaker_role": "local_user",
        "text": "Can you explain Redis?",
        "first_seen_ms": 10,
        "last_updated_ms": 40,
        "finalized_ms": 40,
        "confidence": 0.91,
        "type": "transcript.final",
        "is_final": True,
    }


def test_status_event_accepts_provider_resilience_states() -> None:
    reconnecting = StatusEvent(
        status="reconnecting",
        message="Reconnecting to streaming STT…",
    )
    degraded = StatusEvent(
        status="degraded",
        message="Some audio may not have been transcribed.",
    )

    assert reconnecting.model_dump()["status"] == "reconnecting"
    assert degraded.model_dump()["status"] == "degraded"


def test_session_ready_event_carries_resume_data_additively() -> None:
    event = SessionReadyEvent(
        session_id=SESSION_ID,
        resume_token="opaque-token",
        resumed=True,
        resume_ttl_seconds=30,
    )

    assert event.model_dump(mode="json") == {
        "type": "session.ready",
        "session_id": str(SESSION_ID),
        "resume_token": "opaque-token",
        "resumed": True,
        "resume_ttl_seconds": 30.0,
    }


def test_snapshot_replay_uses_only_latest_canonical_states_in_sequence_order() -> None:
    finalized = utterance(is_final=True)
    active = replace(
        utterance(is_final=False),
        utterance_id=UTTERANCE_ID_TWO,
        sequence=3,
        text="Next active words",
    )
    snapshot = TranscriptSessionSnapshot(
        session_id=SESSION_ID,
        sequence=3,
        active_utterance=active,
        finalized_utterances=(finalized,),
    )

    events = transcript_events_from_snapshot(snapshot)

    assert [event.type for event in events] == [
        "transcript.final",
        "transcript.partial",
    ]
    assert [event.sequence for event in events] == [2, 3]
    assert [event.utterance_id for event in events] == [
        UTTERANCE_ID,
        UTTERANCE_ID_TWO,
    ]
