from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.services.transcript.models import AudioSource, SpeakerRole


class ContinuityQuality(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"


class TurnFinalizationReason(str, Enum):
    MERGE_WINDOW_ELAPSED = "merge_window_elapsed"
    SOURCE_CHANGED = "source_changed"
    STOP_REQUESTED = "stop_requested"
    BROWSER_DISCONNECTED = "browser_disconnected"
    PROVIDER_FAILED = "provider_failed"
    SESSION_RESET = "session_reset"


class AssistanceKind(str, Enum):
    NONE = "none"
    QUESTION = "question"
    REQUEST = "request"


def _validate_source_provenance(
    utterance_ids: tuple[UUID, ...],
    transcript_sequences: tuple[int, ...],
) -> None:
    if not utterance_ids:
        raise ValueError("at least one source utterance is required")
    if len(utterance_ids) != len(transcript_sequences):
        raise ValueError("source IDs and transcript sequences must align")
    if len(set(utterance_ids)) != len(utterance_ids):
        raise ValueError("source utterance IDs must be unique")
    if any(sequence < 1 for sequence in transcript_sequences):
        raise ValueError("source transcript sequences must be positive")
    if any(
        current <= previous
        for previous, current in zip(
            transcript_sequences,
            transcript_sequences[1:],
            strict=False,
        )
    ):
        raise ValueError("source transcript sequences must be strictly increasing")


@dataclass(slots=True, frozen=True)
class ActiveConversationTurn:
    """Read-only evolving turn state for diagnostics and future prediction."""

    session_id: UUID
    turn_id: UUID
    turn_sequence: int
    source_utterance_ids: tuple[UUID, ...]
    source_transcript_sequences: tuple[int, ...]
    audio_source: AudioSource
    speaker_role: SpeakerRole
    text: str
    started_ms: int
    last_updated_ms: int
    continuity_quality: ContinuityQuality
    awaiting_finalization: bool
    pending_deadline_ms: int | None

    def __post_init__(self) -> None:
        if self.turn_sequence < 1:
            raise ValueError("turn_sequence must start at 1")
        _validate_source_provenance(
            self.source_utterance_ids,
            self.source_transcript_sequences,
        )
        if not self.text.strip():
            raise ValueError("active turn text must not be empty")
        if self.started_ms < 0 or self.last_updated_ms < self.started_ms:
            raise ValueError("active turn timing must be monotonic")
        if self.awaiting_finalization != (self.pending_deadline_ms is not None):
            raise ValueError("pending deadline must match finalization state")
        if (
            self.pending_deadline_ms is not None
            and self.pending_deadline_ms < self.last_updated_ms
        ):
            raise ValueError("pending deadline must not precede the last update")


@dataclass(slots=True, frozen=True)
class ConversationTurn:
    """Immutable finalized turn derived only from canonical utterances."""

    session_id: UUID
    turn_id: UUID
    turn_sequence: int
    source_utterance_ids: tuple[UUID, ...]
    source_transcript_sequences: tuple[int, ...]
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

    def __post_init__(self) -> None:
        if self.turn_sequence < 1:
            raise ValueError("turn_sequence must start at 1")
        _validate_source_provenance(
            self.source_utterance_ids,
            self.source_transcript_sequences,
        )
        if not self.text.strip():
            raise ValueError("finalized turn text must not be empty")
        if self.started_ms < 0 or self.last_updated_ms < self.started_ms:
            raise ValueError("turn timing must be monotonic")
        if self.source_finalized_ms < self.last_updated_ms:
            raise ValueError("source finalization must not precede its last update")
        if self.finalized_ms < self.source_finalized_ms:
            raise ValueError("turn finalization must not precede source finalization")
        expected_latency = self.finalized_ms - self.source_finalized_ms
        if self.transcript_final_to_turn_ms != expected_latency:
            raise ValueError("transcript-to-turn latency does not match timing fields")


@dataclass(slots=True, frozen=True)
class AssistanceDecision:
    """Replaceable detector result; only positive decisions become browser events."""

    detection_id: UUID
    session_id: UUID
    source_turn_id: UUID
    source_turn_sequence: int
    should_assist: bool
    kind: AssistanceKind
    detected_ms: int
    turn_to_detection_ms: int
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.source_turn_sequence < 1:
            raise ValueError("source_turn_sequence must be positive")
        if self.detected_ms < 0 or self.turn_to_detection_ms < 0:
            raise ValueError("detection timing must not be negative")
        if self.should_assist == (self.kind is AssistanceKind.NONE):
            raise ValueError("assistance kind must agree with should_assist")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must be omitted or non-empty")


@dataclass(slots=True, frozen=True)
class ConversationSnapshot:
    """Replayable derived state owned by one logical Mentara session."""

    session_id: UUID
    turn_sequence: int
    active_turn: ActiveConversationTurn | None
    finalized_turns: tuple[ConversationTurn, ...]
    assistance_detections: tuple[AssistanceDecision, ...]

    def __post_init__(self) -> None:
        if self.turn_sequence < 0:
            raise ValueError("turn_sequence must not be negative")
        if any(turn.session_id != self.session_id for turn in self.finalized_turns):
            raise ValueError("finalized turns must belong to the snapshot session")
        if self.active_turn is not None and self.active_turn.session_id != self.session_id:
            raise ValueError("active turn must belong to the snapshot session")
        if any(
            decision.session_id != self.session_id
            for decision in self.assistance_detections
        ):
            raise ValueError("assistance decisions must belong to the snapshot session")
