from uuid import UUID

import pytest

from app.services.answer.lifecycle import AnswerLifecycle, InvalidAnswerTransition
from app.services.answer.models import (
    AnswerFailure,
    AnswerFailureCategory,
    AnswerRequest,
    AnswerState,
    AnswerUsage,
)
from app.services.conversation.models import AssistanceKind


def _request() -> AnswerRequest:
    return AnswerRequest(
        answer_id=UUID("20000000-0000-0000-0000-000000000001"),
        session_id=UUID("00000000-0000-0000-0000-000000000001"),
        detection_id=UUID("30000000-0000-0000-0000-000000000001"),
        source_turn_id=UUID("40000000-0000-0000-0000-000000000001"),
        source_turn_sequence=3,
        assistance_kind=AssistanceKind.QUESTION,
        attempt=1,
        detected_ms=100,
        requested_ms=103,
        question_detected_to_answer_request_ms=3,
    )


def test_ordered_stream_completion_and_latency_metrics() -> None:
    lifecycle = AnswerLifecycle(_request())
    requested = lifecycle.snapshot
    assert requested.state is AnswerState.REQUESTED
    assert requested.revision == 1

    starting = lifecycle.mark_starting(at_ms=105)
    first = lifecycle.append_delta("Redis ", sequence=1, at_ms=125)
    second = lifecycle.append_delta("persists data.", sequence=2, at_ms=130)
    completed = lifecycle.complete(
        at_ms=140,
        usage=AnswerUsage(input_tokens=10, output_tokens=4, total_tokens=14),
    )

    assert starting.state is AnswerState.STARTING
    assert first.state is AnswerState.STREAMING
    assert second.text == "Redis persists data."
    assert completed.state is AnswerState.COMPLETED
    assert completed.revision == 5
    assert completed.stream_sequence == 2
    assert completed.answer_request_to_provider_start_ms == 2
    assert completed.answer_request_to_first_text_ms == 22
    assert completed.question_detected_to_first_text_ms == 25
    assert completed.answer_generation_total_ms == 37


def test_empty_completion_is_honest_completed_answer() -> None:
    lifecycle = AnswerLifecycle(_request())
    lifecycle.mark_starting(at_ms=105)
    completed = lifecycle.complete(at_ms=110)
    assert completed.state is AnswerState.COMPLETED
    assert completed.text == ""
    assert completed.first_text_ms is None


@pytest.mark.parametrize("terminal", ("cancel", "supersede", "fail"))
def test_terminal_answers_reject_late_deltas(terminal: str) -> None:
    lifecycle = AnswerLifecycle(_request())
    lifecycle.mark_starting(at_ms=105)
    lifecycle.append_delta("partial", sequence=1, at_ms=110)

    if terminal == "cancel":
        snapshot = lifecycle.cancel(at_ms=115)
        assert snapshot.state is AnswerState.CANCELLED
    elif terminal == "supersede":
        snapshot = lifecycle.supersede(at_ms=115)
        assert snapshot.state is AnswerState.SUPERSEDED
    else:
        snapshot = lifecycle.fail(
            AnswerFailure(
                category=AnswerFailureCategory.PROVIDER_SERVER,
                safe_message="Answer provider failed.",
                retryable=True,
            ),
            at_ms=115,
        )
        assert snapshot.state is AnswerState.FAILED

    with pytest.raises(InvalidAnswerTransition, match="terminal|transition"):
        lifecycle.append_delta("late", sequence=2, at_ms=120)
    with pytest.raises(InvalidAnswerTransition, match="terminal|transition"):
        lifecycle.complete(at_ms=120)


def test_duplicate_stale_and_out_of_order_deltas_are_rejected() -> None:
    lifecycle = AnswerLifecycle(_request())
    lifecycle.mark_starting(at_ms=105)
    lifecycle.append_delta("one", sequence=1, at_ms=110)

    for sequence in (1, 3):
        with pytest.raises(InvalidAnswerTransition, match="expected 2"):
            lifecycle.append_delta("bad", sequence=sequence, at_ms=111)

    assert lifecycle.snapshot.text == "one"
    assert lifecycle.snapshot.stream_sequence == 1


def test_invalid_transitions_do_not_mutate_revision() -> None:
    lifecycle = AnswerLifecycle(_request())
    with pytest.raises(InvalidAnswerTransition, match="expected starting"):
        lifecycle.complete(at_ms=104)
    assert lifecycle.snapshot.revision == 1

    lifecycle.cancel(at_ms=105)
    with pytest.raises(InvalidAnswerTransition, match="terminal"):
        lifecycle.cancel(at_ms=106)
    assert lifecycle.snapshot.revision == 2
