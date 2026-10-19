from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from uuid import UUID

from app.services.conversation.models import ContinuityQuality
from app.services.memory.models import ContextTrust, MemoryContinuity
from app.services.transcript.models import AudioSource, SpeakerRole


MAX_PREDICTION_CANDIDATES = 5
MAX_PREDICTION_CANDIDATE_CHARS = 240
MAX_PREDICTION_ANCHOR_TERMS = 8
MAX_PREDICTION_ANCHOR_TERM_CHARS = 64
MAX_PREDICTION_CONTEXT_CHARS = 6_000
MAX_PREDICTION_CONTEXT_TURN_CHARS = 4_000
MAX_PREDICTION_OUTPUT_TOKENS = 512

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class PredictionCandidateKind(str, Enum):
    QUESTION = "question"
    REQUEST = "request"
    TOPIC = "topic"


class PredictionState(str, Enum):
    IDLE = "idle"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    READY = "ready"
    INVALIDATED = "invalidated"
    FAILED = "failed"


class PredictionReadiness(str, Enum):
    """Operational consistency state, never statistical confidence."""

    TENTATIVE = "tentative"
    STABLE = "stable"


class PredictionInvalidationReason(str, Enum):
    ACTIVE_INPUT_CHANGED = "active_input_changed"
    ACTIVE_PROVENANCE_CHANGED = "active_provenance_changed"
    NEW_ACTIVE_TURN = "new_active_turn"
    SOURCE_OR_SPEAKER_CHANGED = "source_or_speaker_changed"
    MEMORY_REVISION_CHANGED = "memory_revision_changed"
    TURN_FINALIZED = "turn_finalized"
    CONTINUITY_DEGRADED = "continuity_degraded"
    BROWSER_DISCONNECTED = "browser_disconnected"
    STOP_REQUESTED = "stop_requested"
    SESSION_RESET = "session_reset"
    SESSION_EXPIRED = "session_expired"
    BACKEND_SHUTDOWN = "backend_shutdown"
    TURN_ATTEMPT_LIMIT = "turn_attempt_limit"
    SESSION_CALL_LIMIT = "session_call_limit"
    CONTEXT_UNAVAILABLE = "context_unavailable"


class PredictionTriggerReason(str, Enum):
    ELIGIBLE = "eligible"
    NO_ACTIVE_TURN = "no_active_turn"
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    BACKCHANNEL = "backchannel"
    ORDINARY_STATEMENT = "ordinary_statement"
    INSUFFICIENT_SIGNAL = "insufficient_signal"
    CONTINUITY_UNSAFE = "continuity_unsafe"
    MINIMUM_CALL_INTERVAL = "minimum_call_interval"
    UNCHANGED = "unchanged"
    COMPATIBLE_EXTENSION = "compatible_extension"
    BROWSER_DETACHED = "browser_detached"
    TURN_ATTEMPT_LIMIT = "turn_attempt_limit"
    SESSION_CALL_LIMIT = "session_call_limit"


class PredictionFailureCategory(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TRANSIENT_NETWORK = "transient_network"
    PROVIDER_SERVER = "provider_server"
    MALFORMED_OUTPUT = "malformed_output"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    SAFETY_REFUSAL = "safety_refusal"
    UNKNOWN = "unknown"


class PredictionContextSelectionReason(str, Enum):
    ACTIVE_TURN = "active_turn"
    RECENT_MEMORY = "recent_memory"
    RELEVANT_OLDER_MEMORY = "relevant_older_memory"


def _validate_source_provenance(
    source_utterance_ids: tuple[UUID, ...],
    source_transcript_sequences: tuple[int, ...],
) -> None:
    if not source_utterance_ids:
        raise ValueError("prediction provenance requires a source utterance")
    if len(source_utterance_ids) != len(source_transcript_sequences):
        raise ValueError("prediction source provenance must align")
    if len(set(source_utterance_ids)) != len(source_utterance_ids):
        raise ValueError("prediction source utterance IDs must be unique")
    if any(sequence < 1 for sequence in source_transcript_sequences):
        raise ValueError("prediction transcript sequences must be positive")
    if any(
        current <= previous
        for previous, current in zip(
            source_transcript_sequences,
            source_transcript_sequences[1:],
            strict=False,
        )
    ):
        raise ValueError("prediction transcript sequences must increase")


def _validate_fingerprint(value: str) -> None:
    if _SHA256_HEX.fullmatch(value) is None:
        raise ValueError("material fingerprint must be lowercase SHA-256 hex")


@dataclass(slots=True, frozen=True)
class PredictionCandidate:
    kind: PredictionCandidateKind
    text: str
    anchor_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PredictionCandidateKind):
            raise ValueError("prediction candidate kind is invalid")
        if not isinstance(self.text, str) or not isinstance(self.anchor_terms, tuple):
            raise ValueError("prediction candidate fields have invalid types")
        if not self.text.strip() or self.text != self.text.strip():
            raise ValueError("prediction candidate text must be trimmed and non-empty")
        if len(self.text) > MAX_PREDICTION_CANDIDATE_CHARS:
            raise ValueError("prediction candidate text exceeds its absolute bound")
        if len(self.anchor_terms) > MAX_PREDICTION_ANCHOR_TERMS:
            raise ValueError("prediction candidate has too many anchor terms")
        if len(set(self.anchor_terms)) != len(self.anchor_terms):
            raise ValueError("prediction anchor terms must be unique")
        if any(
            not isinstance(term, str)
            or not term
            or term != term.strip()
            or len(term) > MAX_PREDICTION_ANCHOR_TERM_CHARS
            for term in self.anchor_terms
        ):
            raise ValueError("prediction anchor terms must be trimmed and bounded")


@dataclass(slots=True, frozen=True)
class PredictionUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(value is not None and value < 0 for value in values):
            raise ValueError("prediction token usage must not be negative")
        if (
            self.total_tokens is not None
            and self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens < self.input_tokens + self.output_tokens
        ):
            raise ValueError("prediction total tokens cannot be smaller than its parts")


@dataclass(slots=True, frozen=True)
class PredictionFailure:
    category: PredictionFailureCategory
    safe_message: str
    retryable: bool

    def __post_init__(self) -> None:
        if not self.safe_message.strip():
            raise ValueError("prediction failure message must not be empty")


@dataclass(slots=True, frozen=True)
class PredictionContextTurn:
    turn_id: UUID
    turn_sequence: int
    source_utterance_ids: tuple[UUID, ...]
    source_transcript_sequences: tuple[int, ...]
    audio_source: AudioSource
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    text: str
    original_text_chars: int
    text_truncated: bool
    selection_reason: PredictionContextSelectionReason
    trust: ContextTrust = ContextTrust.UNTRUSTED

    def __post_init__(self) -> None:
        if self.turn_sequence < 1:
            raise ValueError("prediction context turn sequence must be positive")
        _validate_source_provenance(
            self.source_utterance_ids,
            self.source_transcript_sequences,
        )
        if not self.text.strip():
            raise ValueError("prediction context text must not be empty")
        if len(self.text) > MAX_PREDICTION_CONTEXT_TURN_CHARS:
            raise ValueError("prediction context turn exceeds its absolute bound")
        if self.original_text_chars < len(self.text):
            raise ValueError("prediction original text length cannot be smaller")
        if self.text_truncated != (self.original_text_chars > len(self.text)):
            raise ValueError("prediction context truncation metadata is inconsistent")
        if self.trust is not ContextTrust.UNTRUSTED:
            raise ValueError("M5.5 conversation prediction context is untrusted")


@dataclass(slots=True, frozen=True)
class PredictionContext:
    session_id: UUID
    prediction_id: UUID
    input_revision: int
    memory_revision: int
    memory_continuity: MemoryContinuity
    active_turn: PredictionContextTurn
    recent_memory: tuple[PredictionContextTurn, ...]
    relevant_older_memory: tuple[PredictionContextTurn, ...]
    total_text_chars: int
    evicted_turn_count: int
    missing_turn_count: int

    def __post_init__(self) -> None:
        if self.input_revision < 1 or self.memory_revision < 0:
            raise ValueError("prediction context revisions are invalid")
        if (
            self.active_turn.selection_reason
            is not PredictionContextSelectionReason.ACTIVE_TURN
        ):
            raise ValueError("prediction active turn must be marked as active")
        if any(
            turn.selection_reason
            is not PredictionContextSelectionReason.RECENT_MEMORY
            for turn in self.recent_memory
        ):
            raise ValueError("prediction recent memory has an invalid reason")
        if any(
            turn.selection_reason
            is not PredictionContextSelectionReason.RELEVANT_OLDER_MEMORY
            for turn in self.relevant_older_memory
        ):
            raise ValueError("prediction older memory has an invalid reason")
        selected = self.relevant_older_memory + self.recent_memory
        if any(
            turn.turn_sequence >= self.active_turn.turn_sequence for turn in selected
        ):
            raise ValueError("prediction memory must precede its active turn")
        ids = tuple(turn.turn_id for turn in selected) + (self.active_turn.turn_id,)
        if len(set(ids)) != len(ids):
            raise ValueError("prediction context turns must be unique")
        for group in (self.relevant_older_memory, self.recent_memory):
            sequences = tuple(turn.turn_sequence for turn in group)
            if sequences != tuple(sorted(set(sequences))):
                raise ValueError("prediction context groups must be ordered and unique")
        expected_chars = len(self.active_turn.text) + sum(
            len(turn.text) for turn in selected
        )
        if self.total_text_chars != expected_chars:
            raise ValueError("prediction context character count does not match")
        if self.total_text_chars > MAX_PREDICTION_CONTEXT_CHARS:
            raise ValueError("prediction context exceeds its absolute bound")
        if self.evicted_turn_count < 0 or self.missing_turn_count < 0:
            raise ValueError("prediction memory gap counts must not be negative")


@dataclass(slots=True, frozen=True)
class PredictionRequest:
    prediction_id: UUID
    session_id: UUID
    active_turn_id: UUID
    active_turn_sequence: int
    input_revision: int
    attempt: int
    material_fingerprint: str
    memory_revision: int
    source_utterance_ids: tuple[UUID, ...]
    source_transcript_sequences: tuple[int, ...]
    triggering_utterance_id: UUID
    triggering_transcript_sequence: int
    triggering_transcript_revision: int
    triggering_utterance_is_final: bool
    audio_source: AudioSource
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    active_turn_started_ms: int
    input_observed_ms: int
    requested_ms: int
    active_turn_to_prediction_request_ms: int
    context: PredictionContext

    def __post_init__(self) -> None:
        if self.active_turn_sequence < 1:
            raise ValueError("prediction active turn sequence must be positive")
        if self.input_revision < 1 or self.attempt < 1:
            raise ValueError("prediction revision and attempt must be positive")
        if self.memory_revision < 0:
            raise ValueError("prediction memory revision must not be negative")
        _validate_fingerprint(self.material_fingerprint)
        _validate_source_provenance(
            self.source_utterance_ids,
            self.source_transcript_sequences,
        )
        if self.triggering_utterance_id not in self.source_utterance_ids:
            raise ValueError("triggering utterance must belong to the active turn")
        index = self.source_utterance_ids.index(self.triggering_utterance_id)
        if (
            self.source_transcript_sequences[index]
            != self.triggering_transcript_sequence
        ):
            raise ValueError("triggering transcript sequence does not match provenance")
        if self.triggering_transcript_revision < 1:
            raise ValueError("triggering transcript revision must be positive")
        if (
            self.active_turn_started_ms < 0
            or self.input_observed_ms < self.active_turn_started_ms
            or self.requested_ms < self.input_observed_ms
        ):
            raise ValueError("prediction request timing must be monotonic")
        if self.active_turn_to_prediction_request_ms != (
            self.requested_ms - self.active_turn_started_ms
        ):
            raise ValueError("active-turn-to-request timing does not match")
        if self.context.session_id != self.session_id:
            raise ValueError("prediction context belongs to another session")
        if self.context.prediction_id != self.prediction_id:
            raise ValueError("prediction context belongs to another prediction")
        if self.context.input_revision != self.input_revision:
            raise ValueError("prediction context input revision does not match")
        if self.context.memory_revision != self.memory_revision:
            raise ValueError("prediction context memory revision does not match")
        if self.context.active_turn.turn_id != self.active_turn_id:
            raise ValueError("prediction context active turn does not match")
        context_active = self.context.active_turn
        if (
            context_active.turn_sequence != self.active_turn_sequence
            or context_active.source_utterance_ids != self.source_utterance_ids
            or context_active.source_transcript_sequences
            != self.source_transcript_sequences
            or context_active.audio_source is not self.audio_source
            or context_active.speaker_role is not self.speaker_role
            or context_active.continuity_quality is not self.continuity_quality
        ):
            raise ValueError("prediction context active provenance does not match")

    @property
    def input_to_prediction_request_ms(self) -> int:
        return self.requested_ms - self.input_observed_ms


@dataclass(slots=True, frozen=True)
class PredictionPrompt:
    """Trusted application policy and untrusted content stay separate."""

    system_instruction: str
    user_content: str

    def __post_init__(self) -> None:
        if not isinstance(self.system_instruction, str) or not isinstance(
            self.user_content,
            str,
        ):
            raise ValueError("prediction prompt fields must be strings")
        if not self.system_instruction.strip() or not self.user_content.strip():
            raise ValueError("prediction prompt sections must not be empty")


@dataclass(slots=True, frozen=True)
class PredictionSnapshot:
    prediction_id: UUID
    session_id: UUID
    active_turn_id: UUID
    active_turn_sequence: int
    input_revision: int
    attempt: int
    state: PredictionState
    snapshot_revision: int
    material_fingerprint: str
    memory_revision: int
    audio_source: AudioSource
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    active_turn_awaiting_finalization: bool
    candidate_consistent_revision_count: int
    candidates: tuple[PredictionCandidate, ...]
    input_observed_ms: int
    scheduled_ms: int | None = None
    provider_started_ms: int | None = None
    ready_ms: int | None = None
    terminal_ms: int | None = None
    readiness: PredictionReadiness | None = None
    invalidation_reason: PredictionInvalidationReason | None = None
    failure: PredictionFailure | None = None
    usage: PredictionUsage | None = None
    context_chars: int | None = None

    def __post_init__(self) -> None:
        if self.state is PredictionState.IDLE:
            raise ValueError("idle is represented by an empty session snapshot")
        if self.active_turn_sequence < 1 or self.input_revision < 1:
            raise ValueError("prediction snapshot provenance must be positive")
        if self.attempt < 0 or self.snapshot_revision < 1:
            raise ValueError("prediction attempt/revision is invalid")
        if self.memory_revision < 0 or self.input_observed_ms < 0:
            raise ValueError("prediction snapshot timing/revision is invalid")
        if self.context_chars is not None and not (
            1 <= self.context_chars <= MAX_PREDICTION_CONTEXT_CHARS
        ):
            raise ValueError("prediction context character metric is invalid")
        if self.candidate_consistent_revision_count < 0:
            raise ValueError("candidate consistency count must not be negative")
        _validate_fingerprint(self.material_fingerprint)
        if len(self.candidates) > MAX_PREDICTION_CANDIDATES:
            raise ValueError("prediction snapshot has too many candidates")
        if any(
            not isinstance(candidate, PredictionCandidate)
            for candidate in self.candidates
        ):
            raise ValueError("prediction snapshot candidate type is invalid")
        candidate_keys = tuple(
            (candidate.kind, candidate.text.casefold()) for candidate in self.candidates
        )
        if len(set(candidate_keys)) != len(candidate_keys):
            raise ValueError("prediction snapshot candidates must be unique")
        if self.scheduled_ms is not None and self.scheduled_ms < self.input_observed_ms:
            raise ValueError("prediction scheduling cannot precede input")
        if self.provider_started_ms is not None and (
            self.scheduled_ms is None or self.provider_started_ms < self.scheduled_ms
        ):
            raise ValueError("prediction provider start cannot precede scheduling")
        if self.provider_started_ms is not None and self.attempt < 1:
            raise ValueError("provider timing requires a positive prediction attempt")
        if self.ready_ms is not None and (
            self.provider_started_ms is None or self.ready_ms < self.provider_started_ms
        ):
            raise ValueError("prediction readiness cannot precede provider start")
        if self.terminal_ms is not None and self.terminal_ms < self.input_observed_ms:
            raise ValueError("prediction terminal time cannot precede input")

        provider_required_states = {
            PredictionState.RUNNING,
            PredictionState.READY,
            PredictionState.FAILED,
        }
        if self.state in provider_required_states and self.attempt < 1:
            raise ValueError("provider state requires a positive prediction attempt")
        if (self.state in provider_required_states) != (
            self.provider_started_ms is not None
        ) and self.state is not PredictionState.INVALIDATED:
            raise ValueError("provider timing must agree with prediction state")
        if (self.state is PredictionState.READY) != (self.ready_ms is not None):
            raise ValueError("ready timing must agree with prediction state")
        terminal = self.state in {
            PredictionState.INVALIDATED,
            PredictionState.FAILED,
        }
        if terminal != (self.terminal_ms is not None):
            raise ValueError("terminal timing must agree with prediction state")
        if (
            self.terminal_ms is not None
            and self.provider_started_ms is not None
            and self.terminal_ms < self.provider_started_ms
        ):
            raise ValueError("prediction terminal time cannot precede provider start")
        if self.state is PredictionState.READY:
            if self.candidates and self.readiness is None:
                raise ValueError("candidate readiness must be explicit")
            if not self.candidates and self.readiness is not None:
                raise ValueError("empty prediction cannot claim readiness")
            if self.candidates and self.candidate_consistent_revision_count < 1:
                raise ValueError("ready candidates require consistency evidence")
            if not self.candidates and self.candidate_consistent_revision_count != 0:
                raise ValueError("empty prediction cannot carry consistency evidence")
        elif (
            self.candidates
            or self.readiness is not None
            or self.usage is not None
            or self.candidate_consistent_revision_count != 0
        ):
            raise ValueError("only ready predictions may carry output")
        if self.readiness is PredictionReadiness.STABLE and (
            not self.candidates
            or self.candidate_consistent_revision_count < 2
            or not self.active_turn_awaiting_finalization
            or self.continuity_quality is not ContinuityQuality.NORMAL
        ):
            raise ValueError("stable readiness lacks operational evidence")
        if (self.state is PredictionState.INVALIDATED) != (
            self.invalidation_reason is not None
        ):
            raise ValueError("invalidation reason must agree with prediction state")
        if (self.state is PredictionState.FAILED) != (self.failure is not None):
            raise ValueError("failure must agree with prediction state")
        if self.context_chars is not None and self.attempt < 1:
            raise ValueError("prediction context metric requires an attempt")

    @property
    def prediction_request_to_ready_ms(self) -> int | None:
        if self.ready_ms is None or self.provider_started_ms is None:
            return None
        return self.ready_ms - self.provider_started_ms


@dataclass(slots=True, frozen=True)
class PredictionSessionSnapshot:
    session_id: UUID
    state: PredictionState
    current: PredictionSnapshot | None
    provider_attempt_count: int
    stale_discard_count: int
    cancelled_call_count: int
    suppressed_observation_count: int = 0
    last_trigger_reason: PredictionTriggerReason | None = None

    def __post_init__(self) -> None:
        values = (
            self.provider_attempt_count,
            self.stale_discard_count,
            self.cancelled_call_count,
            self.suppressed_observation_count,
        )
        if any(value < 0 for value in values):
            raise ValueError("prediction session counters must not be negative")
        if (self.state is PredictionState.IDLE) != (self.current is None):
            raise ValueError("idle prediction session must have no current snapshot")
        if self.current is not None:
            if self.current.session_id != self.session_id:
                raise ValueError("prediction belongs to another session")
            if self.current.state is not self.state:
                raise ValueError(
                    "prediction session state does not match current state"
                )
