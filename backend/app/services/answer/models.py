from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias
from uuid import UUID

from app.services.conversation.models import AssistanceKind, ContinuityQuality
from app.services.memory.models import ContextProvenance, MemoryContinuity
from app.services.transcript.models import SpeakerRole


class AnswerState(str, Enum):
    REQUESTED = "requested"
    STARTING = "starting"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            AnswerState.COMPLETED,
            AnswerState.CANCELLED,
            AnswerState.SUPERSEDED,
            AnswerState.FAILED,
        }


class AnswerFailureCategory(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TRANSIENT_NETWORK = "transient_network"
    PROVIDER_SERVER = "provider_server"
    MALFORMED_STREAM = "malformed_stream"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    SAFETY_REFUSAL = "safety_refusal"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class AnswerUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("token usage must not be negative")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens < self.input_tokens + self.output_tokens
        ):
            raise ValueError("total token usage cannot be smaller than its parts")


@dataclass(slots=True, frozen=True)
class AnswerFailure:
    category: AnswerFailureCategory
    safe_message: str
    retryable: bool

    def __post_init__(self) -> None:
        if not self.safe_message.strip():
            raise ValueError("safe failure message must not be empty")


@dataclass(slots=True, frozen=True)
class AnswerRequest:
    """Stable request derived from authoritative M3 turn/detection objects."""

    answer_id: UUID
    session_id: UUID
    detection_id: UUID
    source_turn_id: UUID
    source_turn_sequence: int
    assistance_kind: AssistanceKind
    attempt: int
    detected_ms: int
    requested_ms: int
    question_detected_to_answer_request_ms: int

    def __post_init__(self) -> None:
        if self.source_turn_sequence < 1:
            raise ValueError("source_turn_sequence must be positive")
        if self.assistance_kind is AssistanceKind.NONE:
            raise ValueError("answer requests require a positive assistance kind")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        if self.detected_ms < 0 or self.requested_ms < self.detected_ms:
            raise ValueError("answer request timing must be monotonic")
        if (
            self.question_detected_to_answer_request_ms
            != self.requested_ms - self.detected_ms
        ):
            raise ValueError("detection-to-request latency does not match timing")


@dataclass(slots=True, frozen=True)
class AnswerContextTurn:
    turn_id: UUID
    turn_sequence: int
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    text: str
    text_truncated: bool = False
    provenance: ContextProvenance | None = None

    def __post_init__(self) -> None:
        if self.turn_sequence < 1:
            raise ValueError("context turn sequence must be positive")
        if not self.text.strip():
            raise ValueError("context turn text must not be empty")


@dataclass(slots=True, frozen=True)
class AnswerContext:
    """Small provider-neutral context; it is not provider conversation memory."""

    session_id: UUID
    answer_id: UUID
    assistance_kind: AssistanceKind
    source_turn: AnswerContextTurn
    recent_turns: tuple[AnswerContextTurn, ...]
    total_text_chars: int
    relevant_older_turns: tuple[AnswerContextTurn, ...] = ()
    memory_revision: int | None = None
    memory_continuity: MemoryContinuity | None = None
    evicted_turn_count: int = 0
    missing_turn_count: int = 0

    def __post_init__(self) -> None:
        if self.assistance_kind is AssistanceKind.NONE:
            raise ValueError("answer context requires a positive assistance kind")
        selected = self.relevant_older_turns + self.recent_turns
        if self.total_text_chars != len(self.source_turn.text) + sum(
            len(turn.text) for turn in selected
        ):
            raise ValueError("context character count does not match its turns")
        if any(
            turn.turn_sequence >= self.source_turn.turn_sequence
            for turn in selected
        ):
            raise ValueError("context turns must precede the source turn")
        ids = tuple(turn.turn_id for turn in selected) + (self.source_turn.turn_id,)
        if len(set(ids)) != len(ids):
            raise ValueError("context turns must be unique")
        for group in (self.relevant_older_turns, self.recent_turns):
            sequences = tuple(turn.turn_sequence for turn in group)
            if sequences != tuple(sorted(set(sequences))):
                raise ValueError("context turn groups must be unique and ordered")
        memory_fields = (self.memory_revision, self.memory_continuity)
        if any(value is None for value in memory_fields) != all(
            value is None for value in memory_fields
        ):
            raise ValueError("memory context metadata must be provided together")
        if self.memory_revision is not None and self.memory_revision < 0:
            raise ValueError("memory revision must not be negative")
        if self.evicted_turn_count < 0 or self.missing_turn_count < 0:
            raise ValueError("memory context gap counts must not be negative")
        if self.memory_revision is None and (
            self.relevant_older_turns
            or self.evicted_turn_count
            or self.missing_turn_count
        ):
            raise ValueError("M4 context cannot carry M5 memory fields")


@dataclass(slots=True, frozen=True)
class AnswerPrompt:
    """Policy and untrusted user content remain structurally separate."""

    system_instruction: str
    user_content: str

    def __post_init__(self) -> None:
        if not self.system_instruction.strip() or not self.user_content.strip():
            raise ValueError("answer prompt sections must not be empty")


@dataclass(slots=True, frozen=True)
class AnswerProviderTextDelta:
    sequence: int
    text: str

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("provider stream sequence must be positive")
        if not self.text:
            raise ValueError("provider text delta must not be empty")


@dataclass(slots=True, frozen=True)
class AnswerProviderCompleted:
    sequence: int
    usage: AnswerUsage | None = None
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("provider stream sequence must be positive")
        if self.finish_reason is not None and not self.finish_reason.strip():
            raise ValueError("finish_reason must be omitted or non-empty")


AnswerProviderEvent: TypeAlias = AnswerProviderTextDelta | AnswerProviderCompleted


@dataclass(slots=True, frozen=True)
class AnswerSnapshot:
    answer_id: UUID
    session_id: UUID
    detection_id: UUID
    source_turn_id: UUID
    source_turn_sequence: int
    attempt: int
    state: AnswerState
    revision: int
    stream_sequence: int
    text: str
    requested_ms: int
    question_detected_to_answer_request_ms: int
    provider_started_ms: int | None = None
    first_text_ms: int | None = None
    terminal_ms: int | None = None
    usage: AnswerUsage | None = None
    failure: AnswerFailure | None = None

    def __post_init__(self) -> None:
        if self.source_turn_sequence < 1 or self.attempt < 1:
            raise ValueError("answer provenance must be positive")
        if self.revision < 1 or self.stream_sequence < 0:
            raise ValueError("answer revision/sequence is invalid")
        if self.requested_ms < 0:
            raise ValueError("requested_ms must not be negative")
        if self.provider_started_ms is not None and (
            self.provider_started_ms < self.requested_ms
        ):
            raise ValueError("provider start cannot precede the answer request")
        if self.first_text_ms is not None and (
            self.provider_started_ms is None
            or self.first_text_ms < self.provider_started_ms
        ):
            raise ValueError("first text cannot precede provider start")
        if self.state is AnswerState.STREAMING and self.first_text_ms is None:
            raise ValueError("streaming state requires first-text timing")
        if self.state.is_terminal != (self.terminal_ms is not None):
            raise ValueError("terminal timing must agree with answer state")
        if self.terminal_ms is not None and self.terminal_ms < self.requested_ms:
            raise ValueError("terminal time cannot precede the answer request")
        if self.state is AnswerState.FAILED and self.failure is None:
            raise ValueError("failed state requires a sanitized failure")
        if self.state is not AnswerState.FAILED and self.failure is not None:
            raise ValueError("only failed answers may carry a failure")
        if self.state is not AnswerState.COMPLETED and self.usage is not None:
            raise ValueError("usage is attached only to completed answers")

    @property
    def answer_request_to_provider_start_ms(self) -> int | None:
        if self.provider_started_ms is None:
            return None
        return self.provider_started_ms - self.requested_ms

    @property
    def answer_request_to_first_text_ms(self) -> int | None:
        if self.first_text_ms is None:
            return None
        return self.first_text_ms - self.requested_ms

    @property
    def question_detected_to_first_text_ms(self) -> int | None:
        request_latency = self.answer_request_to_first_text_ms
        if request_latency is None:
            return None
        return self.question_detected_to_answer_request_ms + request_latency

    @property
    def answer_generation_total_ms(self) -> int | None:
        if self.state is not AnswerState.COMPLETED or self.terminal_ms is None:
            return None
        return self.terminal_ms - self.requested_ms


@dataclass(slots=True, frozen=True)
class AnswerSessionSnapshot:
    session_id: UUID
    answers: tuple[AnswerSnapshot, ...]
    active_answer_id: UUID | None

    def __post_init__(self) -> None:
        if any(answer.session_id != self.session_id for answer in self.answers):
            raise ValueError("answers must belong to the snapshot session")
        answer_ids = tuple(answer.answer_id for answer in self.answers)
        if len(set(answer_ids)) != len(answer_ids):
            raise ValueError("answer snapshot identities must be unique")
        if self.active_answer_id is not None:
            matching = [
                answer
                for answer in self.answers
                if answer.answer_id == self.active_answer_id
            ]
            if len(matching) != 1 or matching[0].state.is_terminal:
                raise ValueError("active answer identity must refer to active state")
