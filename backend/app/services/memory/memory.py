from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import RLock
from uuid import UUID

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import ContinuityQuality, ConversationTurn
from app.services.memory.models import (
    ContextProvenance,
    ContextSourceKind,
    ContextTrust,
    MemoryContinuity,
    MemoryEntry,
    MemoryObservationStatus,
    MemorySequenceGap,
    MemorySnapshot,
)
from app.services.memory.terms import (
    DeterministicTopicTermExtractor,
    TopicTermExtractor,
)


class MemorySessionMismatchError(ValueError):
    pass


class MemoryInvariantError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class MemoryLimits:
    max_retained_turns: int = 256
    max_retained_text_chars: int = 160_000
    max_entry_text_chars: int = 4_000

    def __post_init__(self) -> None:
        if self.max_retained_turns < 1:
            raise ValueError("memory retained-turn limit must be positive")
        if self.max_retained_text_chars < 1:
            raise ValueError("memory retained-character limit must be positive")
        if self.max_entry_text_chars < 1:
            raise ValueError("memory entry-character limit must be positive")
        if self.max_entry_text_chars > self.max_retained_text_chars:
            raise ValueError("memory entry limit cannot exceed total character limit")


class ConversationMemory:
    """Bounded logical-session memory derived only from finalized M3 turns."""

    def __init__(
        self,
        *,
        session_id: UUID,
        limits: MemoryLimits | None = None,
        term_extractor: TopicTermExtractor | None = None,
    ) -> None:
        self._session_id = session_id
        self._limits = limits or MemoryLimits()
        self._term_extractor = term_extractor or DeterministicTopicTermExtractor()
        self._entries: deque[MemoryEntry] = deque()
        self._retained_ids: set[UUID] = set()
        self._stored_text_chars = 0
        self._memory_revision = 0
        self._last_committed_sequence = 0
        self._evicted_turn_count = 0
        self._evicted_through_turn_sequence: int | None = None
        self._missing_turn_count = 0
        self._latest_sequence_gap: MemorySequenceGap | None = None
        self._cleared = False
        self._lock = RLock()

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def limits(self) -> MemoryLimits:
        return self._limits

    def observe(self, turn: ConversationTurn) -> MemoryObservationStatus:
        with self._lock:
            if self._cleared:
                raise RuntimeError("conversation memory has been released")
            if turn.session_id != self._session_id:
                raise MemorySessionMismatchError(
                    "conversation turn belongs to another logical session"
                )
            expected_turn_id = derive_turn_id(self._session_id, turn.turn_sequence)
            if turn.turn_id != expected_turn_id:
                raise MemoryInvariantError(
                    "conversation turn identity does not match its stable sequence"
                )
            if turn.turn_id in self._retained_ids:
                return MemoryObservationStatus.DUPLICATE
            if turn.turn_sequence <= self._last_committed_sequence:
                return MemoryObservationStatus.STALE_IGNORED

            if turn.turn_sequence > self._last_committed_sequence + 1:
                gap = MemorySequenceGap(
                    missing_from_sequence=self._last_committed_sequence + 1,
                    missing_through_sequence=turn.turn_sequence - 1,
                )
                self._latest_sequence_gap = gap
                self._missing_turn_count += gap.missing_turn_count

            entry = self._entry(turn)
            self._entries.append(entry)
            self._retained_ids.add(entry.turn_id)
            self._stored_text_chars += len(entry.text)
            self._last_committed_sequence = turn.turn_sequence
            self._memory_revision += 1
            self._evict_to_limits()
            return MemoryObservationStatus.COMMITTED

    def snapshot(self) -> MemorySnapshot:
        with self._lock:
            entries = tuple(self._entries)
            degraded = (
                self._evicted_turn_count > 0
                or self._missing_turn_count > 0
                or any(
                    entry.continuity_quality is ContinuityQuality.DEGRADED
                    for entry in entries
                )
            )
            return MemorySnapshot(
                session_id=self._session_id,
                memory_revision=self._memory_revision,
                entries=entries,
                stored_turn_count=len(entries),
                stored_text_chars=self._stored_text_chars,
                continuity=(
                    MemoryContinuity.DEGRADED
                    if degraded
                    else MemoryContinuity.NORMAL
                ),
                evicted_turn_count=self._evicted_turn_count,
                evicted_through_turn_sequence=self._evicted_through_turn_sequence,
                missing_turn_count=self._missing_turn_count,
                latest_sequence_gap=self._latest_sequence_gap,
            )

    def reset(self, *, session_id: UUID) -> MemorySnapshot:
        with self._lock:
            self._session_id = session_id
            self._entries.clear()
            self._retained_ids.clear()
            self._stored_text_chars = 0
            self._memory_revision = 0
            self._last_committed_sequence = 0
            self._evicted_turn_count = 0
            self._evicted_through_turn_sequence = None
            self._missing_turn_count = 0
            self._latest_sequence_gap = None
            self._cleared = False
            return self.snapshot()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._retained_ids.clear()
            self._stored_text_chars = 0
            self._evicted_turn_count = 0
            self._evicted_through_turn_sequence = None
            self._missing_turn_count = 0
            self._latest_sequence_gap = None
            self._cleared = True

    def _entry(self, turn: ConversationTurn) -> MemoryEntry:
        stripped = turn.text.strip()
        text = _truncate(stripped, self._limits.max_entry_text_chars)
        return MemoryEntry(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            turn_sequence=turn.turn_sequence,
            source_utterance_ids=turn.source_utterance_ids,
            source_transcript_sequences=turn.source_transcript_sequences,
            audio_source=turn.audio_source,
            speaker_role=turn.speaker_role,
            continuity_quality=turn.continuity_quality,
            text=text,
            original_text_chars=len(stripped),
            text_truncated=len(text) < len(stripped),
            topic_terms=self._term_extractor.extract(text),
            provenance=ContextProvenance(
                source_kind=ContextSourceKind.VERBATIM_CONVERSATION,
                trust=ContextTrust.UNTRUSTED,
                source_turn_ids=(turn.turn_id,),
                source_turn_sequence_start=turn.turn_sequence,
                source_turn_sequence_end=turn.turn_sequence,
            ),
        )

    def _evict_to_limits(self) -> None:
        while self._entries and (
            len(self._entries) > self._limits.max_retained_turns
            or self._stored_text_chars > self._limits.max_retained_text_chars
        ):
            evicted = self._entries.popleft()
            self._retained_ids.remove(evicted.turn_id)
            self._stored_text_chars -= len(evicted.text)
            self._evicted_turn_count += 1
            self._evicted_through_turn_sequence = evicted.turn_sequence


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return f"{text[: limit - 1]}…"
