from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.services.answer.identity import derive_answer_id
from app.services.answer.models import AnswerState
from app.services.answer.request import build_answer_request
from app.services.conversation.identity import (
    derive_assistance_detection_id,
    derive_turn_id,
)
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
UTTERANCE_ID = UUID("10000000-0000-0000-0000-000000000001")


def _turn(*, sequence: int = 1) -> ConversationTurn:
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text="Explain Redis persistence.",
        started_ms=100,
        last_updated_ms=150,
        source_finalized_ms=150,
        finalized_ms=400,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=250,
    )


def _decision(turn: ConversationTurn, *, positive: bool = True) -> AssistanceDecision:
    return AssistanceDecision(
        detection_id=derive_assistance_detection_id(turn.turn_id),
        session_id=turn.session_id,
        source_turn_id=turn.turn_id,
        source_turn_sequence=turn.turn_sequence,
        should_assist=positive,
        kind=AssistanceKind.REQUEST if positive else AssistanceKind.NONE,
        detected_ms=401,
        turn_to_detection_ms=1,
    )


def test_positive_detection_builds_one_stable_answer_request() -> None:
    turn = _turn()
    decision = _decision(turn)
    first = build_answer_request(decision, turn, requested_ms=403)
    replay = build_answer_request(decision, turn, requested_ms=410)

    assert first.answer_id == derive_answer_id(decision.detection_id)
    assert replay.answer_id == first.answer_id
    assert replay.detection_id == decision.detection_id
    assert replay.source_turn_id == turn.turn_id
    assert first.question_detected_to_answer_request_ms == 2
    assert first.attempt == 1


def test_request_is_immutable_and_future_attempt_keeps_logical_identity() -> None:
    turn = _turn()
    decision = _decision(turn)
    first = build_answer_request(decision, turn, requested_ms=402)
    regeneration = build_answer_request(decision, turn, requested_ms=403, attempt=2)

    assert first.answer_id == regeneration.answer_id
    assert regeneration.attempt == 2
    with pytest.raises(FrozenInstanceError):
        first.attempt = 3  # type: ignore[misc]


def test_negative_or_mismatched_detection_cannot_build_request() -> None:
    turn = _turn()
    with pytest.raises(ValueError, match="negative"):
        build_answer_request(_decision(turn, positive=False), turn, requested_ms=402)

    other_turn = _turn(sequence=2)
    with pytest.raises(ValueError, match="does not refer"):
        build_answer_request(_decision(turn), other_turn, requested_ms=402)


def test_answer_states_distinguish_all_terminal_outcomes() -> None:
    assert AnswerState.COMPLETED.is_terminal
    assert AnswerState.CANCELLED.is_terminal
    assert AnswerState.SUPERSEDED.is_terminal
    assert AnswerState.FAILED.is_terminal
    assert not AnswerState.REQUESTED.is_terminal
    assert not AnswerState.STARTING.is_terminal
    assert not AnswerState.STREAMING.is_terminal
