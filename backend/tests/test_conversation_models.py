from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.services.conversation.identity import (
    derive_assistance_detection_id,
    derive_turn_id,
)
from app.services.conversation.models import (
    ActiveConversationTurn,
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


def finalized_turn() -> ConversationTurn:
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, 1),
        turn_sequence=1,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(3,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="Can you explain Redis?",
        started_ms=100,
        last_updated_ms=180,
        source_finalized_ms=180,
        finalized_ms=430,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=250,
    )


def test_turn_and_detection_ids_are_stable_and_namespaced() -> None:
    first = derive_turn_id(SESSION_ID, 1)
    assert first == derive_turn_id(SESSION_ID, 1)
    assert first != derive_turn_id(SESSION_ID, 2)
    assert derive_assistance_detection_id(first) == derive_assistance_detection_id(
        first
    )


def test_finalized_turn_is_immutable_and_validates_latency() -> None:
    turn = finalized_turn()
    with pytest.raises(FrozenInstanceError):
        turn.text = "Changed"  # type: ignore[misc]

    payload = {
        field: getattr(turn, field)
        for field in turn.__dataclass_fields__
    }
    payload["transcript_final_to_turn_ms"] = 249
    with pytest.raises(ValueError, match="latency"):
        ConversationTurn(**payload)


def test_active_turn_exposes_pending_state_for_future_prediction() -> None:
    active = ActiveConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, 1),
        turn_sequence=1,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(2,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="Can you explain",
        started_ms=100,
        last_updated_ms=150,
        continuity_quality=ContinuityQuality.DEGRADED,
        awaiting_finalization=False,
        pending_deadline_ms=None,
    )

    snapshot = ConversationSnapshot(
        session_id=SESSION_ID,
        turn_sequence=1,
        active_turn=active,
        finalized_turns=(),
        assistance_detections=(),
    )
    assert snapshot.active_turn == active
    assert snapshot.active_turn.continuity_quality is ContinuityQuality.DEGRADED


def test_assistance_contract_rejects_inconsistent_kind() -> None:
    turn = finalized_turn()
    with pytest.raises(ValueError, match="agree"):
        AssistanceDecision(
            detection_id=derive_assistance_detection_id(turn.turn_id),
            session_id=SESSION_ID,
            source_turn_id=turn.turn_id,
            source_turn_sequence=turn.turn_sequence,
            should_assist=False,
            kind=AssistanceKind.QUESTION,
            detected_ms=430,
            turn_to_detection_ms=0,
        )


def test_snapshot_rejects_cross_session_derived_state() -> None:
    turn = finalized_turn()
    with pytest.raises(ValueError, match="snapshot session"):
        ConversationSnapshot(
            session_id=UUID("00000000-0000-0000-0000-000000000002"),
            turn_sequence=1,
            active_turn=None,
            finalized_turns=(turn,),
            assistance_detections=(),
        )
