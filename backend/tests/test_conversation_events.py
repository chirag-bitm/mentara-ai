from uuid import UUID

import pytest

from app.schemas.events import (
    conversation_events_from_snapshot,
    question_event_from_decision,
    turn_event_from_turn,
)
from app.services.conversation.identity import (
    derive_assistance_detection_id,
    derive_turn_id,
)
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ContinuityQuality,
    ConversationSnapshot,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
UTTERANCE_ID = UUID("10000000-0000-0000-0000-000000000001")


def turn() -> ConversationTurn:
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, 1),
        turn_sequence=1,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(3,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="Can you explain Redis?",
        started_ms=10,
        last_updated_ms=20,
        source_finalized_ms=20,
        finalized_ms=270,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.DEGRADED,
        transcript_final_to_turn_ms=250,
    )


def decision(should_assist: bool = True) -> AssistanceDecision:
    source = turn()
    return AssistanceDecision(
        detection_id=derive_assistance_detection_id(source.turn_id),
        session_id=SESSION_ID,
        source_turn_id=source.turn_id,
        source_turn_sequence=1,
        should_assist=should_assist,
        kind=AssistanceKind.QUESTION if should_assist else AssistanceKind.NONE,
        detected_ms=271,
        turn_to_detection_ms=1,
        reason="interrogative_cue" if should_assist else "no_actionable_cue",
    )


def test_turn_event_carries_canonical_provenance_quality_and_latency() -> None:
    payload = turn_event_from_turn(turn()).model_dump(mode="json")
    assert payload["type"] == "turn.finalized"
    assert payload["source_utterance_ids"] == [str(UTTERANCE_ID)]
    assert payload["source_transcript_sequences"] == [3]
    assert payload["continuity_quality"] == "degraded"
    assert payload["transcript_final_to_turn_ms"] == 250


def test_question_event_refers_to_source_turn_without_copying_text() -> None:
    payload = question_event_from_decision(decision()).model_dump(mode="json")
    assert payload["type"] == "question.detected"
    assert payload["kind"] == "question"
    assert payload["source_turn_id"] == str(turn().turn_id)
    assert "text" not in payload
    assert "confidence" not in payload


def test_negative_decision_cannot_become_browser_event() -> None:
    with pytest.raises(ValueError, match="positive"):
        question_event_from_decision(decision(False))


def test_snapshot_replay_orders_turns_before_positive_detections() -> None:
    source = turn()
    snapshot = ConversationSnapshot(
        session_id=SESSION_ID,
        turn_sequence=1,
        active_turn=None,
        finalized_turns=(source,),
        assistance_detections=(decision(),),
    )
    events = conversation_events_from_snapshot(snapshot)
    assert [event.type for event in events] == [
        "turn.finalized",
        "question.detected",
    ]
