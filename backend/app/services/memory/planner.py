from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from uuid import UUID

from app.services.conversation.models import ContinuityQuality
from app.services.memory.models import (
    ContextProvenance,
    MemoryContinuity,
    MemoryEntry,
    MemorySnapshot,
)
from app.services.memory.terms import (
    DeterministicTopicTermExtractor,
    TopicTermExtractor,
)
from app.services.transcript.models import SpeakerRole


class ContextSelectionReason(str, Enum):
    SOURCE = "source"
    RECENT = "recent"
    RELEVANT_OLDER = "relevant_older"


@dataclass(slots=True, frozen=True)
class ContextPlannerLimits:
    max_recent_turns: int = 4
    max_relevant_older_turns: int = 4
    max_total_text_chars: int = 6_000
    max_turn_text_chars: int = 2_000

    def __post_init__(self) -> None:
        if self.max_recent_turns < 0 or self.max_relevant_older_turns < 0:
            raise ValueError("context planner turn limits must not be negative")
        if self.max_total_text_chars < 1 or self.max_turn_text_chars < 1:
            raise ValueError("context planner character limits must be positive")


@dataclass(slots=True, frozen=True)
class PlannedContextTurn:
    turn_id: UUID
    turn_sequence: int
    speaker_role: SpeakerRole
    continuity_quality: ContinuityQuality
    text: str
    text_truncated: bool
    selection_reason: ContextSelectionReason
    provenance: ContextProvenance

    def __post_init__(self) -> None:
        if self.turn_sequence < 1 or not self.text.strip():
            raise ValueError("planned context turn must be non-empty and ordered")


@dataclass(slots=True, frozen=True)
class PlannedMemoryContext:
    session_id: UUID
    memory_revision: int
    memory_continuity: MemoryContinuity
    source_turn: PlannedContextTurn
    recent_turns: tuple[PlannedContextTurn, ...]
    relevant_older_turns: tuple[PlannedContextTurn, ...]
    total_text_chars: int
    evicted_turn_count: int
    missing_turn_count: int

    def __post_init__(self) -> None:
        if self.source_turn.selection_reason is not ContextSelectionReason.SOURCE:
            raise ValueError("planned source turn must be marked as source")
        if any(
            turn.selection_reason is not ContextSelectionReason.RECENT
            for turn in self.recent_turns
        ):
            raise ValueError("recent context has an invalid selection reason")
        if any(
            turn.selection_reason is not ContextSelectionReason.RELEVANT_OLDER
            for turn in self.relevant_older_turns
        ):
            raise ValueError("older context has an invalid selection reason")
        selected = self.relevant_older_turns + self.recent_turns
        if any(turn.turn_sequence >= self.source_turn.turn_sequence for turn in selected):
            raise ValueError("selected context must precede the source turn")
        ids = tuple(turn.turn_id for turn in selected) + (self.source_turn.turn_id,)
        if len(set(ids)) != len(ids):
            raise ValueError("planned context turns must be unique")
        for group in (self.relevant_older_turns, self.recent_turns):
            sequences = tuple(turn.turn_sequence for turn in group)
            if sequences != tuple(sorted(sequences)):
                raise ValueError("planned context groups must be chronological")
        expected_chars = len(self.source_turn.text) + sum(
            len(turn.text) for turn in selected
        )
        if self.total_text_chars != expected_chars:
            raise ValueError("planned context character count does not match")


class ContextPlanner(Protocol):
    def plan(
        self,
        snapshot: MemorySnapshot,
        *,
        source_turn_id: UUID,
    ) -> PlannedMemoryContext: ...


class DeterministicContextPlanner:
    """Bounded recent plus local exact-term relevance selection."""

    def __init__(
        self,
        *,
        limits: ContextPlannerLimits | None = None,
        term_extractor: TopicTermExtractor | None = None,
    ) -> None:
        self._limits = limits or ContextPlannerLimits()
        self._term_extractor = term_extractor or DeterministicTopicTermExtractor()

    @property
    def limits(self) -> ContextPlannerLimits:
        return self._limits

    def plan(
        self,
        snapshot: MemorySnapshot,
        *,
        source_turn_id: UUID,
    ) -> PlannedMemoryContext:
        source_entry = next(
            (entry for entry in snapshot.entries if entry.turn_id == source_turn_id),
            None,
        )
        if source_entry is None:
            raise ValueError("source turn is not available in conversation memory")

        preceding = tuple(
            entry
            for entry in snapshot.entries
            if entry.turn_sequence < source_entry.turn_sequence
        )
        recent_entries = preceding[-self._limits.max_recent_turns :]
        if self._limits.max_recent_turns == 0:
            recent_entries = ()
        recent_ids = {entry.turn_id for entry in recent_entries}
        older_candidates = tuple(
            entry for entry in preceding if entry.turn_id not in recent_ids
        )
        relevant_entries = self._relevant(source_entry, older_candidates)

        source, remaining = self._bounded_turn(
            source_entry,
            ContextSelectionReason.SOURCE,
            remaining=self._limits.max_total_text_chars,
        )
        recent = self._fit_recent(recent_entries, remaining)
        remaining -= sum(len(turn.text) for turn in recent)
        relevant = self._fit_ranked_relevant(relevant_entries, remaining)

        return PlannedMemoryContext(
            session_id=snapshot.session_id,
            memory_revision=snapshot.memory_revision,
            memory_continuity=snapshot.continuity,
            source_turn=source,
            recent_turns=recent,
            relevant_older_turns=relevant,
            total_text_chars=(
                len(source.text)
                + sum(len(turn.text) for turn in recent)
                + sum(len(turn.text) for turn in relevant)
            ),
            evicted_turn_count=snapshot.evicted_turn_count,
            missing_turn_count=snapshot.missing_turn_count,
        )

    def _relevant(
        self,
        source: MemoryEntry,
        candidates: tuple[MemoryEntry, ...],
    ) -> tuple[MemoryEntry, ...]:
        # Stored terms are the efficient reusable topic/entity foundation.
        # Re-extract only when derived metadata is unexpectedly empty so one
        # stale/legacy entry cannot silently disable retrieval.
        query_terms = set(
            source.topic_terms or self._term_extractor.extract(source.text)
        )
        if not query_terms or self._limits.max_relevant_older_turns == 0:
            return ()
        scored: list[tuple[int, int, MemoryEntry]] = []
        for entry in candidates:
            candidate_terms = set(
                entry.topic_terms or self._term_extractor.extract(entry.text)
            )
            overlap = query_terms.intersection(candidate_terms)
            if overlap:
                scored.append((len(overlap), entry.turn_sequence, entry))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return tuple(
            item[2]
            for item in scored[: self._limits.max_relevant_older_turns]
        )

    def _fit_recent(
        self,
        entries: tuple[MemoryEntry, ...],
        remaining: int,
    ) -> tuple[PlannedContextTurn, ...]:
        selected: list[PlannedContextTurn] = []
        for entry in reversed(entries):
            if remaining <= 0:
                break
            turn, remaining = self._bounded_turn(
                entry,
                ContextSelectionReason.RECENT,
                remaining=remaining,
            )
            selected.append(turn)
        return tuple(reversed(selected))

    def _fit_ranked_relevant(
        self,
        entries: tuple[MemoryEntry, ...],
        remaining: int,
    ) -> tuple[PlannedContextTurn, ...]:
        selected: list[PlannedContextTurn] = []
        for entry in entries:
            if remaining <= 0:
                break
            turn, remaining = self._bounded_turn(
                entry,
                ContextSelectionReason.RELEVANT_OLDER,
                remaining=remaining,
            )
            selected.append(turn)
        selected.sort(key=lambda turn: turn.turn_sequence)
        return tuple(selected)

    def _bounded_turn(
        self,
        entry: MemoryEntry,
        reason: ContextSelectionReason,
        *,
        remaining: int,
    ) -> tuple[PlannedContextTurn, int]:
        limit = min(self._limits.max_turn_text_chars, remaining)
        text, additionally_truncated = _truncate(entry.text, limit)
        turn = PlannedContextTurn(
            turn_id=entry.turn_id,
            turn_sequence=entry.turn_sequence,
            speaker_role=entry.speaker_role,
            continuity_quality=entry.continuity_quality,
            text=text,
            text_truncated=entry.text_truncated or additionally_truncated,
            selection_reason=reason,
            provenance=entry.provenance,
        )
        return turn, remaining - len(text)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if limit < 1:
        raise ValueError("context turn cannot fit in the remaining budget")
    if len(text) <= limit:
        return text, False
    if limit == 1:
        return "…", True
    return f"{text[: limit - 1]}…", True
