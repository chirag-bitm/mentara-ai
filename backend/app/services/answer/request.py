from app.services.answer.identity import derive_answer_id
from app.services.answer.models import AnswerRequest
from app.services.conversation.models import AssistanceDecision, ConversationTurn


def build_answer_request(
    decision: AssistanceDecision,
    source_turn: ConversationTurn,
    *,
    requested_ms: int,
    attempt: int = 1,
) -> AnswerRequest:
    """Build an answer request from authoritative M3 domain objects only."""

    if not decision.should_assist:
        raise ValueError("a negative assistance decision cannot request an answer")
    if decision.session_id != source_turn.session_id:
        raise ValueError("decision and source turn must belong to the same session")
    if decision.source_turn_id != source_turn.turn_id:
        raise ValueError("decision does not refer to the supplied source turn")
    if decision.source_turn_sequence != source_turn.turn_sequence:
        raise ValueError("decision/source turn sequence mismatch")

    return AnswerRequest(
        answer_id=derive_answer_id(decision.detection_id),
        session_id=decision.session_id,
        detection_id=decision.detection_id,
        source_turn_id=decision.source_turn_id,
        source_turn_sequence=decision.source_turn_sequence,
        assistance_kind=decision.kind,
        attempt=attempt,
        detected_ms=decision.detected_ms,
        requested_ms=requested_ms,
        question_detected_to_answer_request_ms=requested_ms - decision.detected_ms,
    )
