from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.services.conversation.models import ContinuityQuality
from app.services.transcript.models import AudioSource, SpeakerRole


class ContextSourceKind(str, Enum):
    VERBATIM_CONVERSATION = "verbatim_conversation"
    DERIVED_MEMORY = "derived_memory"
    FUTURE_VERIFIED_CONTEXT = "future_verified_context"


class ContextTrust(str, Enum):
    UNTRUSTED = "untrusted"
    VERIFIED = "verified"


class MemoryContinuity(str, Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"


class MemoryObservationStatus(str, Enum):
    COMMITTED = "committed"
    DUPLICATE = "duplicate"
    STALE_IGNORED = "stale_ignored"


@dataclass(slots=True, frozen=True)
class ContextProvenance:
    source_kind: ContextSourceKind
    trust: ContextTrust
    source_turn_ids: tuple[UUID, ...]
    source_turn_sequence_start: int | None
    source_turn_sequence_end: int | None

    def __post_init__(self) -> None:
        if len(set(self.source_turn_ids)) != len(self.source_turn_ids):
            raise ValueError("context provenance turn IDs must be unique")
        if self.source_kind in {
            ContextSourceKind.VERBATIM_CONVERSATION,
            ContextSourceKind.DERIVED_MEMORY,
        }:
            if self.trust is not ContextTrust.UNTRUSTED:
                raise ValueError("conversation and derived memory must remain untrusted")
            if not self.source_turn_ids:
                raise ValueError("conversation provenance requires a source turn")
            if self.source_turn_sequence_start is None:
                raise ValueError("conversation provenance requires a sequence range")
            if self.source_turn_sequence_end is None:
                raise ValueError("conversation provenance requires a sequence range")
        elif self.trust is not ContextTrust.VERIFIED:
            raise ValueError("future verified context must use verified trust")
        if (self.source_turn_sequence_start is None) != (
            self.source_turn_sequence_end is None
        ):
            raise ValueError("context provenance sequence range must be complete")
        if self.source_turn_sequence_start is not None:
            if self.source_turn_sequence_start < 1:
                raise ValueError("context provenance sequence must be positive")
            if self.source_turn_sequence_end < self.source_turn_sequence_start:
                raise ValueError("context provenance sequence range is invalid")


@dataclass(slots=True, frozen=True)
class MemorySequenceGap:
    missing_from_sequence: int
    missing_through_sequence: int

    def __post_init__(self) -> None:
        if self.missing_from_sequence < 1:
            raise ValueError("memory gap sequence must be positive")
        if self.missing_through_sequence < self.missing_from_sequence:
            raise ValueError("memory gap sequence range is invalid")

    @property
    def missing_turn_count(self) -> int:
        return self.missing_through_sequence - self.missing_from_sequence + 1


@dataclass(slots=True, frozen=True)
class MemoryEntry:
    session_id: UUID
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
    topic_terms: tuple[str, ...]
    provenance: ContextProvenance

    def __post_init__(self) -> None:
        if self.turn_sequence < 1:
            raise ValueError("memory turn sequence must be positive")
        if not self.text.strip():
            raise ValueError("memory text must not be empty")
        if not self.source_utterance_ids:
            raise ValueError("memory entry requires source utterance provenance")
        if len(self.source_utterance_ids) != len(self.source_transcript_sequences):
            raise ValueError("memory source provenance must align")
        if any(sequence < 1 for sequence in self.source_transcript_sequences):
            raise ValueError("memory transcript sequences must be positive")
        if self.original_text_chars < len(self.text):
            raise ValueError("original memory text length cannot be smaller")
        if self.text_truncated != (self.original_text_chars > len(self.text)):
            raise ValueError("memory truncation metadata does not match text length")
        if self.provenance.source_kind is not ContextSourceKind.VERBATIM_CONVERSATION:
            raise ValueError("M5 memory entries must be verbatim conversation")
        if self.provenance.trust is not ContextTrust.UNTRUSTED:
            raise ValueError("M5 memory entries must remain untrusted")
        if self.provenance.source_turn_ids != (self.turn_id,):
            raise ValueError("memory provenance must reference its source turn")
        if (
            self.provenance.source_turn_sequence_start != self.turn_sequence
            or self.provenance.source_turn_sequence_end != self.turn_sequence
        ):
            raise ValueError("memory provenance sequence must match its turn")
        if len(set(self.topic_terms)) != len(self.topic_terms):
            raise ValueError("memory topic terms must be unique")
        if any(not term or len(term) > 64 for term in self.topic_terms):
            raise ValueError("memory topic terms must be non-empty and bounded")


@dataclass(slots=True, frozen=True)
class MemorySnapshot:
    session_id: UUID
    memory_revision: int
    entries: tuple[MemoryEntry, ...]
    stored_turn_count: int
    stored_text_chars: int
    continuity: MemoryContinuity
    evicted_turn_count: int
    evicted_through_turn_sequence: int | None
    missing_turn_count: int
    latest_sequence_gap: MemorySequenceGap | None

    def __post_init__(self) -> None:
        if self.memory_revision < 0:
            raise ValueError("memory revision must not be negative")
        if self.stored_turn_count != len(self.entries):
            raise ValueError("stored memory turn count does not match entries")
        if self.stored_text_chars != sum(len(entry.text) for entry in self.entries):
            raise ValueError("stored memory character count does not match entries")
        if any(entry.session_id != self.session_id for entry in self.entries):
            raise ValueError("memory entries must belong to the snapshot session")
        sequences = tuple(entry.turn_sequence for entry in self.entries)
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("memory entries must be unique and ordered")
        if self.evicted_turn_count < 0 or self.missing_turn_count < 0:
            raise ValueError("memory gap counters must not be negative")
        if (self.evicted_turn_count == 0) != (
            self.evicted_through_turn_sequence is None
        ):
            raise ValueError("eviction count and boundary must agree")
        if (self.missing_turn_count == 0) != (self.latest_sequence_gap is None):
            raise ValueError("sequence gap count and latest gap must agree")
        degraded = (
            self.evicted_turn_count > 0
            or self.missing_turn_count > 0
            or any(
                entry.continuity_quality is ContinuityQuality.DEGRADED
                for entry in self.entries
            )
        )
        if degraded != (self.continuity is MemoryContinuity.DEGRADED):
            raise ValueError("memory continuity does not match its evidence")
