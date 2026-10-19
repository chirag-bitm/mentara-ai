from __future__ import annotations

from dataclasses import replace

from app.services.answer.models import (
    AnswerFailure,
    AnswerRequest,
    AnswerSnapshot,
    AnswerState,
    AnswerUsage,
)


class InvalidAnswerTransition(ValueError):
    pass


class AnswerLifecycle:
    """Validates all answer state, revision and text-sequence transitions."""

    def __init__(self, request: AnswerRequest) -> None:
        self._snapshot = AnswerSnapshot(
            answer_id=request.answer_id,
            session_id=request.session_id,
            detection_id=request.detection_id,
            source_turn_id=request.source_turn_id,
            source_turn_sequence=request.source_turn_sequence,
            attempt=request.attempt,
            state=AnswerState.REQUESTED,
            revision=1,
            stream_sequence=0,
            text="",
            requested_ms=request.requested_ms,
            question_detected_to_answer_request_ms=(
                request.question_detected_to_answer_request_ms
            ),
        )

    @property
    def snapshot(self) -> AnswerSnapshot:
        return self._snapshot

    def mark_starting(self, *, at_ms: int) -> AnswerSnapshot:
        self._require_state(AnswerState.REQUESTED)
        self._require_time(at_ms)
        return self._commit(
            state=AnswerState.STARTING,
            provider_started_ms=at_ms,
        )

    def append_delta(
        self,
        text: str,
        *,
        sequence: int,
        at_ms: int,
    ) -> AnswerSnapshot:
        self._require_state(AnswerState.STARTING, AnswerState.STREAMING)
        if not text:
            raise ValueError("answer delta must not be empty")
        expected = self._snapshot.stream_sequence + 1
        if sequence != expected:
            raise InvalidAnswerTransition(
                f"answer delta sequence {sequence} does not match expected {expected}"
            )
        self._require_time(at_ms, provider_started=True)
        return self._commit(
            state=AnswerState.STREAMING,
            stream_sequence=sequence,
            text=self._snapshot.text + text,
            first_text_ms=self._snapshot.first_text_ms or at_ms,
        )

    def complete(
        self,
        *,
        at_ms: int,
        usage: AnswerUsage | None = None,
    ) -> AnswerSnapshot:
        self._require_state(AnswerState.STARTING, AnswerState.STREAMING)
        self._require_time(at_ms, provider_started=True)
        return self._commit(
            state=AnswerState.COMPLETED,
            terminal_ms=at_ms,
            usage=usage,
        )

    def cancel(self, *, at_ms: int) -> AnswerSnapshot:
        self._require_non_terminal()
        self._require_time(at_ms)
        return self._commit(state=AnswerState.CANCELLED, terminal_ms=at_ms)

    def supersede(self, *, at_ms: int) -> AnswerSnapshot:
        self._require_non_terminal()
        self._require_time(at_ms)
        return self._commit(state=AnswerState.SUPERSEDED, terminal_ms=at_ms)

    def fail(self, failure: AnswerFailure, *, at_ms: int) -> AnswerSnapshot:
        self._require_non_terminal()
        self._require_time(at_ms)
        return self._commit(
            state=AnswerState.FAILED,
            terminal_ms=at_ms,
            failure=failure,
        )

    def _commit(self, **changes: object) -> AnswerSnapshot:
        self._snapshot = replace(
            self._snapshot,
            revision=self._snapshot.revision + 1,
            **changes,
        )
        return self._snapshot

    def _require_state(self, *allowed: AnswerState) -> None:
        if self._snapshot.state not in allowed:
            allowed_names = ", ".join(state.value for state in allowed)
            raise InvalidAnswerTransition(
                f"cannot transition from {self._snapshot.state.value}; "
                f"expected {allowed_names}"
            )

    def _require_non_terminal(self) -> None:
        if self._snapshot.state.is_terminal:
            raise InvalidAnswerTransition(
                f"answer is already terminal: {self._snapshot.state.value}"
            )

    def _require_time(self, at_ms: int, *, provider_started: bool = False) -> None:
        minimum = self._snapshot.requested_ms
        if provider_started and self._snapshot.provider_started_ms is not None:
            minimum = self._snapshot.provider_started_ms
        if self._snapshot.first_text_ms is not None:
            minimum = max(minimum, self._snapshot.first_text_ms)
        if at_ms < minimum:
            raise ValueError("answer transition timing must be monotonic")
