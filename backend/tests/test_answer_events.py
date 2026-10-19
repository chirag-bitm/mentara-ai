from uuid import UUID

from app.schemas.events import (
    AnswerDeltaEvent,
    AnswerEventProjector,
    AnswerSnapshotEvent,
    answer_events_from_snapshot,
)
from app.services.answer.lifecycle import AnswerLifecycle
from app.services.answer.models import (
    AnswerRequest,
    AnswerSessionSnapshot,
    AnswerState,
)
from app.services.conversation.models import AssistanceKind


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
ANSWER_ID = UUID("20000000-0000-0000-0000-000000000001")


def _request() -> AnswerRequest:
    return AnswerRequest(
        answer_id=ANSWER_ID,
        session_id=SESSION_ID,
        detection_id=UUID("30000000-0000-0000-0000-000000000001"),
        source_turn_id=UUID("40000000-0000-0000-0000-000000000001"),
        source_turn_sequence=1,
        assistance_kind=AssistanceKind.QUESTION,
        attempt=1,
        detected_ms=100,
        requested_ms=102,
        question_detected_to_answer_request_ms=2,
    )


def test_projector_emits_additive_live_events_and_ignores_stale_revision() -> None:
    lifecycle = AnswerLifecycle(_request())
    projector = AnswerEventProjector()
    starting = lifecycle.mark_starting(at_ms=104)
    first = lifecycle.append_delta("Hello", sequence=1, at_ms=110)
    second = lifecycle.append_delta(" world", sequence=2, at_ms=112)
    completed = lifecycle.complete(at_ms=120)

    start_event = projector.project(starting)
    first_event = projector.project(first)
    second_event = projector.project(second)
    completed_event = projector.project(completed)

    assert start_event is not None and start_event.type == "answer.started"
    assert isinstance(first_event, AnswerDeltaEvent)
    assert first_event.from_stream_sequence == 1
    assert first_event.stream_sequence == 1
    assert first_event.text == "Hello"
    assert isinstance(second_event, AnswerDeltaEvent)
    assert second_event.from_stream_sequence == 2
    assert second_event.stream_sequence == 2
    assert second_event.text == " world"
    assert completed_event is not None
    assert completed_event.type == "answer.completed"
    assert projector.project(second) is None


def test_replay_uses_full_idempotent_answer_snapshots() -> None:
    lifecycle = AnswerLifecycle(_request())
    lifecycle.mark_starting(at_ms=104)
    current = lifecycle.append_delta("partial", sequence=1, at_ms=110)
    session_snapshot = AnswerSessionSnapshot(
        session_id=SESSION_ID,
        answers=(current,),
        active_answer_id=ANSWER_ID,
    )

    replayed = answer_events_from_snapshot(session_snapshot)
    assert len(replayed) == 1
    assert isinstance(replayed[0], AnswerSnapshotEvent)
    assert replayed[0].state is AnswerState.STREAMING
    assert replayed[0].text == "partial"
    assert replayed[0].revision == current.revision


def test_projector_falls_back_to_snapshot_when_delta_base_is_unknown() -> None:
    lifecycle = AnswerLifecycle(_request())
    lifecycle.mark_starting(at_ms=104)
    streaming = lifecycle.append_delta("full", sequence=1, at_ms=110)

    projected = AnswerEventProjector().project(streaming)
    assert isinstance(projected, AnswerSnapshotEvent)
    assert projected.text == "full"
