from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerSessionSnapshot,
    AnswerSnapshot,
    AnswerState,
)
from app.services.prediction.models import (
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionInvalidationReason,
    PredictionReadiness,
    PredictionSnapshot,
    PredictionState,
)

from app.services.transcript.models import (
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
    TranscriptSessionSnapshot,
)
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ContinuityQuality,
    ConversationSnapshot,
    ConversationTurn,
    TurnFinalizationReason,
)


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    status: Literal[
        "connecting",
        "ready",
        "reconnecting",
        "degraded",
        "stopping",
        "stopped",
    ]
    message: str


class SessionReadyEvent(BaseModel):
    type: Literal["session.ready"] = "session.ready"
    session_id: UUID
    resume_token: str
    resumed: bool
    resume_ttl_seconds: float


class CanonicalTranscriptPayload(BaseModel):
    session_id: UUID
    utterance_id: UUID
    sequence: int
    revision: int
    audio_source: AudioSource
    speaker_role: SpeakerRole
    text: str
    first_seen_ms: int
    last_updated_ms: int
    finalized_ms: int | None = None
    confidence: float | None = None


class PartialTranscriptEvent(CanonicalTranscriptPayload):
    type: Literal["transcript.partial"] = "transcript.partial"
    is_final: Literal[False] = False


class FinalTranscriptEvent(CanonicalTranscriptPayload):
    type: Literal["transcript.final"] = "transcript.final"
    is_final: Literal[True] = True


def transcript_event_from_utterance(
    utterance: CanonicalUtterance,
) -> PartialTranscriptEvent | FinalTranscriptEvent:
    payload = {
        "session_id": utterance.session_id,
        "utterance_id": utterance.utterance_id,
        "sequence": utterance.sequence,
        "revision": utterance.revision,
        "audio_source": utterance.audio_source,
        "speaker_role": utterance.speaker_role,
        "text": utterance.text,
        "first_seen_ms": utterance.first_seen_ms,
        "last_updated_ms": utterance.last_updated_ms,
        "finalized_ms": utterance.finalized_ms,
        "confidence": utterance.confidence,
    }
    if utterance.is_final:
        return FinalTranscriptEvent(**payload)
    return PartialTranscriptEvent(**payload)


def transcript_events_from_snapshot(
    snapshot: TranscriptSessionSnapshot,
) -> list[PartialTranscriptEvent | FinalTranscriptEvent]:
    utterances = list(snapshot.finalized_utterances)
    if snapshot.active_utterance is not None:
        utterances.append(snapshot.active_utterance)
    utterances.sort(key=lambda utterance: utterance.sequence)
    return [transcript_event_from_utterance(utterance) for utterance in utterances]


class ConversationTurnPayload(BaseModel):
    session_id: UUID
    turn_id: UUID
    turn_sequence: int
    source_utterance_ids: list[UUID]
    source_transcript_sequences: list[int]
    audio_source: AudioSource
    speaker_role: SpeakerRole
    text: str
    started_ms: int
    last_updated_ms: int
    source_finalized_ms: int
    finalized_ms: int
    finalization_reason: TurnFinalizationReason
    continuity_quality: ContinuityQuality
    transcript_final_to_turn_ms: int


class TurnFinalizedEvent(ConversationTurnPayload):
    type: Literal["turn.finalized"] = "turn.finalized"


class QuestionDetectedEvent(BaseModel):
    type: Literal["question.detected"] = "question.detected"
    detection_id: UUID
    session_id: UUID
    source_turn_id: UUID
    source_turn_sequence: int
    kind: AssistanceKind
    detected_ms: int
    turn_to_detection_ms: int


def turn_event_from_turn(turn: ConversationTurn) -> TurnFinalizedEvent:
    return TurnFinalizedEvent(
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        turn_sequence=turn.turn_sequence,
        source_utterance_ids=list(turn.source_utterance_ids),
        source_transcript_sequences=list(turn.source_transcript_sequences),
        audio_source=turn.audio_source,
        speaker_role=turn.speaker_role,
        text=turn.text,
        started_ms=turn.started_ms,
        last_updated_ms=turn.last_updated_ms,
        source_finalized_ms=turn.source_finalized_ms,
        finalized_ms=turn.finalized_ms,
        finalization_reason=turn.finalization_reason,
        continuity_quality=turn.continuity_quality,
        transcript_final_to_turn_ms=turn.transcript_final_to_turn_ms,
    )


def question_event_from_decision(
    decision: AssistanceDecision,
) -> QuestionDetectedEvent:
    if not decision.should_assist or decision.kind is AssistanceKind.NONE:
        raise ValueError("only positive assistance decisions become browser events")
    return QuestionDetectedEvent(
        detection_id=decision.detection_id,
        session_id=decision.session_id,
        source_turn_id=decision.source_turn_id,
        source_turn_sequence=decision.source_turn_sequence,
        kind=decision.kind,
        detected_ms=decision.detected_ms,
        turn_to_detection_ms=decision.turn_to_detection_ms,
    )


def conversation_events_from_snapshot(
    snapshot: ConversationSnapshot,
) -> list[TurnFinalizedEvent | QuestionDetectedEvent]:
    events: list[TurnFinalizedEvent | QuestionDetectedEvent] = [
        turn_event_from_turn(turn) for turn in snapshot.finalized_turns
    ]
    events.extend(
        question_event_from_decision(decision)
        for decision in snapshot.assistance_detections
        if decision.should_assist
    )
    return events


class AnswerEventPayload(BaseModel):
    answer_id: UUID
    session_id: UUID
    detection_id: UUID
    source_turn_id: UUID
    source_turn_sequence: int
    attempt: int
    revision: int
    stream_sequence: int


class AnswerStartedEvent(AnswerEventPayload):
    type: Literal["answer.started"] = "answer.started"
    state: Literal["starting"] = "starting"
    requested_ms: int
    provider_started_ms: int
    question_detected_to_answer_request_ms: int
    answer_request_to_provider_start_ms: int


class AnswerDeltaEvent(AnswerEventPayload):
    type: Literal["answer.delta"] = "answer.delta"
    state: Literal["streaming"] = "streaming"
    from_stream_sequence: int
    text: str
    first_text_ms: int
    answer_request_to_first_text_ms: int
    question_detected_to_first_text_ms: int


class AnswerCompletedEvent(AnswerEventPayload):
    type: Literal["answer.completed"] = "answer.completed"
    state: Literal["completed"] = "completed"
    terminal_ms: int
    answer_generation_total_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AnswerCancelledEvent(AnswerEventPayload):
    type: Literal["answer.cancelled"] = "answer.cancelled"
    state: Literal["cancelled"] = "cancelled"
    terminal_ms: int


class AnswerSupersededEvent(AnswerEventPayload):
    type: Literal["answer.superseded"] = "answer.superseded"
    state: Literal["superseded"] = "superseded"
    terminal_ms: int


class AnswerFailedEvent(AnswerEventPayload):
    type: Literal["answer.failed"] = "answer.failed"
    state: Literal["failed"] = "failed"
    terminal_ms: int
    error_category: AnswerFailureCategory
    message: str
    retryable: bool


class AnswerSnapshotEvent(AnswerEventPayload):
    type: Literal["answer.snapshot"] = "answer.snapshot"
    state: AnswerState
    text: str
    requested_ms: int
    question_detected_to_answer_request_ms: int
    provider_started_ms: int | None = None
    first_text_ms: int | None = None
    terminal_ms: int | None = None
    answer_request_to_provider_start_ms: int | None = None
    answer_request_to_first_text_ms: int | None = None
    question_detected_to_first_text_ms: int | None = None
    answer_generation_total_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    error_category: AnswerFailureCategory | None = None
    message: str | None = None
    retryable: bool | None = None


AnswerBrowserEvent = (
    AnswerStartedEvent
    | AnswerDeltaEvent
    | AnswerCompletedEvent
    | AnswerCancelledEvent
    | AnswerSupersededEvent
    | AnswerFailedEvent
    | AnswerSnapshotEvent
)


def _answer_common(snapshot: AnswerSnapshot) -> dict[str, object]:
    return {
        "answer_id": snapshot.answer_id,
        "session_id": snapshot.session_id,
        "detection_id": snapshot.detection_id,
        "source_turn_id": snapshot.source_turn_id,
        "source_turn_sequence": snapshot.source_turn_sequence,
        "attempt": snapshot.attempt,
        "revision": snapshot.revision,
        "stream_sequence": snapshot.stream_sequence,
    }


def answer_snapshot_event(snapshot: AnswerSnapshot) -> AnswerSnapshotEvent:
    usage = snapshot.usage
    failure = snapshot.failure
    return AnswerSnapshotEvent(
        **_answer_common(snapshot),
        state=snapshot.state,
        text=snapshot.text,
        requested_ms=snapshot.requested_ms,
        question_detected_to_answer_request_ms=(
            snapshot.question_detected_to_answer_request_ms
        ),
        provider_started_ms=snapshot.provider_started_ms,
        first_text_ms=snapshot.first_text_ms,
        terminal_ms=snapshot.terminal_ms,
        answer_request_to_provider_start_ms=(
            snapshot.answer_request_to_provider_start_ms
        ),
        answer_request_to_first_text_ms=snapshot.answer_request_to_first_text_ms,
        question_detected_to_first_text_ms=(
            snapshot.question_detected_to_first_text_ms
        ),
        answer_generation_total_ms=snapshot.answer_generation_total_ms,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        total_tokens=usage.total_tokens if usage is not None else None,
        error_category=failure.category if failure is not None else None,
        message=failure.safe_message if failure is not None else None,
        retryable=failure.retryable if failure is not None else None,
    )


def answer_events_from_snapshot(
    snapshot: AnswerSessionSnapshot,
) -> list[AnswerSnapshotEvent]:
    return [answer_snapshot_event(answer) for answer in snapshot.answers]


class PredictionCandidatePayload(BaseModel):
    kind: PredictionCandidateKind
    text: str
    anchor_terms: list[str]


PredictionBrowserInvalidationReason = Literal[
    "active_input_changed",
    "active_provenance_changed",
    "new_active_turn",
    "source_or_speaker_changed",
    "context_changed",
    "turn_finalized",
    "continuity_degraded",
    "browser_disconnected",
    "stop_requested",
    "session_reset",
    "session_expired",
    "backend_shutdown",
    "turn_attempt_limit",
    "session_call_limit",
    "context_unavailable",
]


class PredictionSnapshotEvent(BaseModel):
    type: Literal["prediction.snapshot"] = "prediction.snapshot"
    prediction_id: UUID
    session_id: UUID
    active_turn_id: UUID
    active_turn_sequence: int
    input_revision: int
    attempt: int
    state: PredictionState
    revision: int
    audio_source: AudioSource
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    active_turn_awaiting_finalization: bool
    candidate_consistent_revision_count: int
    candidates: list[PredictionCandidatePayload]
    input_observed_ms: int
    scheduled_ms: int | None = None
    provider_started_ms: int | None = None
    ready_ms: int | None = None
    terminal_ms: int | None = None
    readiness: PredictionReadiness | None = None
    invalidation_reason: PredictionBrowserInvalidationReason | None = None
    error_category: PredictionFailureCategory | None = None
    message: str | None = None
    retryable: bool | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    context_chars: int | None = None


def prediction_event_from_snapshot(
    snapshot: PredictionSnapshot,
) -> PredictionSnapshotEvent:
    failure = snapshot.failure
    usage = snapshot.usage
    return PredictionSnapshotEvent(
        prediction_id=snapshot.prediction_id,
        session_id=snapshot.session_id,
        active_turn_id=snapshot.active_turn_id,
        active_turn_sequence=snapshot.active_turn_sequence,
        input_revision=snapshot.input_revision,
        attempt=snapshot.attempt,
        state=snapshot.state,
        revision=snapshot.snapshot_revision,
        audio_source=snapshot.audio_source,
        speaker_role=snapshot.speaker_role,
        continuity_quality=snapshot.continuity_quality,
        active_turn_awaiting_finalization=(
            snapshot.active_turn_awaiting_finalization
        ),
        candidate_consistent_revision_count=(
            snapshot.candidate_consistent_revision_count
        ),
        candidates=[
            PredictionCandidatePayload(
                kind=candidate.kind,
                text=candidate.text,
                anchor_terms=list(candidate.anchor_terms),
            )
            for candidate in snapshot.candidates
        ],
        input_observed_ms=snapshot.input_observed_ms,
        scheduled_ms=snapshot.scheduled_ms,
        provider_started_ms=snapshot.provider_started_ms,
        ready_ms=snapshot.ready_ms,
        terminal_ms=snapshot.terminal_ms,
        readiness=snapshot.readiness,
        invalidation_reason=(
            "context_changed"
            if snapshot.invalidation_reason
            is PredictionInvalidationReason.MEMORY_REVISION_CHANGED
            else (
                snapshot.invalidation_reason.value
                if snapshot.invalidation_reason is not None
                else None
            )
        ),
        error_category=failure.category if failure is not None else None,
        message=failure.safe_message if failure is not None else None,
        retryable=failure.retryable if failure is not None else None,
        input_tokens=usage.input_tokens if usage is not None else None,
        output_tokens=usage.output_tokens if usage is not None else None,
        total_tokens=usage.total_tokens if usage is not None else None,
        context_chars=snapshot.context_chars,
    )


class AnswerEventProjector:
    """Turns backend snapshots into additive live events for one browser lease."""

    def __init__(self) -> None:
        self._previous: dict[UUID, AnswerSnapshot] = {}

    def seed(self, snapshot: AnswerSnapshot) -> None:
        current = self._previous.get(snapshot.answer_id)
        if current is None or snapshot.revision > current.revision:
            self._previous[snapshot.answer_id] = snapshot

    def project(self, snapshot: AnswerSnapshot) -> AnswerBrowserEvent | None:
        previous = self._previous.get(snapshot.answer_id)
        if previous is not None and snapshot.revision <= previous.revision:
            return None

        event: AnswerBrowserEvent
        common = _answer_common(snapshot)
        if snapshot.state is AnswerState.STARTING:
            if snapshot.provider_started_ms is None:
                raise ValueError("starting answer lacks provider timing")
            event = AnswerStartedEvent(
                **common,
                requested_ms=snapshot.requested_ms,
                provider_started_ms=snapshot.provider_started_ms,
                question_detected_to_answer_request_ms=(
                    snapshot.question_detected_to_answer_request_ms
                ),
                answer_request_to_provider_start_ms=(
                    snapshot.answer_request_to_provider_start_ms or 0
                ),
            )
        elif snapshot.state is AnswerState.STREAMING:
            if (
                previous is None
                or not snapshot.text.startswith(previous.text)
                or snapshot.stream_sequence <= previous.stream_sequence
            ):
                event = answer_snapshot_event(snapshot)
            else:
                delta = snapshot.text[len(previous.text) :]
                if not delta or snapshot.first_text_ms is None:
                    raise ValueError("streaming snapshot does not add text")
                event = AnswerDeltaEvent(
                    **common,
                    from_stream_sequence=previous.stream_sequence + 1,
                    text=delta,
                    first_text_ms=snapshot.first_text_ms,
                    answer_request_to_first_text_ms=(
                        snapshot.answer_request_to_first_text_ms or 0
                    ),
                    question_detected_to_first_text_ms=(
                        snapshot.question_detected_to_first_text_ms or 0
                    ),
                )
        elif snapshot.state is AnswerState.COMPLETED:
            if snapshot.terminal_ms is None:
                raise ValueError("completed answer lacks terminal timing")
            usage = snapshot.usage
            event = AnswerCompletedEvent(
                **common,
                terminal_ms=snapshot.terminal_ms,
                answer_generation_total_ms=snapshot.answer_generation_total_ms or 0,
                input_tokens=usage.input_tokens if usage is not None else None,
                output_tokens=usage.output_tokens if usage is not None else None,
                total_tokens=usage.total_tokens if usage is not None else None,
            )
        elif snapshot.state is AnswerState.CANCELLED:
            if snapshot.terminal_ms is None:
                raise ValueError("cancelled answer lacks terminal timing")
            event = AnswerCancelledEvent(
                **common,
                terminal_ms=snapshot.terminal_ms,
            )
        elif snapshot.state is AnswerState.SUPERSEDED:
            if snapshot.terminal_ms is None:
                raise ValueError("superseded answer lacks terminal timing")
            event = AnswerSupersededEvent(
                **common,
                terminal_ms=snapshot.terminal_ms,
            )
        elif snapshot.state is AnswerState.FAILED:
            if snapshot.terminal_ms is None or snapshot.failure is None:
                raise ValueError("failed answer lacks failure detail")
            event = AnswerFailedEvent(
                **common,
                terminal_ms=snapshot.terminal_ms,
                error_category=snapshot.failure.category,
                message=snapshot.failure.safe_message,
                retryable=snapshot.failure.retryable,
            )
        else:
            event = answer_snapshot_event(snapshot)

        self._previous[snapshot.answer_id] = snapshot
        return event


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class PongEvent(BaseModel):
    type: Literal["pong"] = "pong"
    message: str = "WebSocket connection is working."
