from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.conversation.models import ActiveConversationTurn
from app.services.memory.models import MemoryEntry, MemorySnapshot
from app.services.memory.terms import (
    DeterministicTopicTermExtractor,
    TopicTermExtractor,
)
from app.services.prediction.identity import derive_prediction_id
from app.services.prediction.models import (
    MAX_PREDICTION_CONTEXT_CHARS,
    MAX_PREDICTION_CONTEXT_TURN_CHARS,
    PredictionContext,
    PredictionContextSelectionReason,
    PredictionContextTurn,
)


@dataclass(slots=True, frozen=True)
class PredictionContextPlannerLimits:
    """Operational bounds below the absolute domain safety ceilings."""

    max_recent_turns: int = 2
    max_relevant_older_turns: int = 2
    max_total_text_chars: int = 3_200
    max_active_turn_chars: int = 1_200
    max_memory_turn_chars: int = 800

    def __post_init__(self) -> None:
        if self.max_recent_turns < 0 or self.max_relevant_older_turns < 0:
            raise ValueError("prediction context turn limits must not be negative")
        if not 1 <= self.max_total_text_chars <= MAX_PREDICTION_CONTEXT_CHARS:
            raise ValueError("prediction context total-character limit is invalid")
        for value, label in (
            (self.max_active_turn_chars, "active-turn"),
            (self.max_memory_turn_chars, "memory-turn"),
        ):
            if not 1 <= value <= MAX_PREDICTION_CONTEXT_TURN_CHARS:
                raise ValueError(f"prediction {label} character limit is invalid")
            if value > self.max_total_text_chars:
                raise ValueError(
                    f"prediction {label} limit cannot exceed total context"
                )


class PredictionContextPlanner(Protocol):
    def plan(
        self,
        snapshot: MemorySnapshot,
        active_turn: ActiveConversationTurn,
        *,
        input_revision: int,
    ) -> PredictionContext: ...


class DeterministicPredictionContextPlanner:
    """Read-only active/recent/relevant context selection for prediction."""

    def __init__(
        self,
        *,
        limits: PredictionContextPlannerLimits | None = None,
        term_extractor: TopicTermExtractor | None = None,
    ) -> None:
        self._limits = limits or PredictionContextPlannerLimits()
        self._term_extractor = term_extractor or DeterministicTopicTermExtractor()

    @property
    def limits(self) -> PredictionContextPlannerLimits:
        return self._limits

    def plan(
        self,
        snapshot: MemorySnapshot,
        active_turn: ActiveConversationTurn,
        *,
        input_revision: int,
    ) -> PredictionContext:
        if snapshot.session_id != active_turn.session_id:
            raise ValueError("prediction memory and active turn must share a session")
        if input_revision < 1:
            raise ValueError("prediction context input revision must be positive")

        preceding = tuple(
            entry
            for entry in snapshot.entries
            if entry.turn_sequence < active_turn.turn_sequence
        )
        recent_entries = (
            preceding[-self._limits.max_recent_turns :]
            if self._limits.max_recent_turns
            else ()
        )
        recent_ids = {entry.turn_id for entry in recent_entries}
        older_entries = tuple(
            entry for entry in preceding if entry.turn_id not in recent_ids
        )
        relevant_entries = self._relevant(active_turn, older_entries)

        active, remaining = self._active_context(
            active_turn,
            remaining=self._limits.max_total_text_chars,
        )
        recent, remaining = self._fit_recent(recent_entries, remaining)
        relevant, remaining = self._fit_relevant(relevant_entries, remaining)
        del remaining

        return PredictionContext(
            session_id=active_turn.session_id,
            prediction_id=derive_prediction_id(
                active_turn.session_id,
                active_turn.turn_id,
            ),
            input_revision=input_revision,
            memory_revision=snapshot.memory_revision,
            memory_continuity=snapshot.continuity,
            active_turn=active,
            recent_memory=recent,
            relevant_older_memory=relevant,
            total_text_chars=(
                len(active.text)
                + sum(len(turn.text) for turn in recent)
                + sum(len(turn.text) for turn in relevant)
            ),
            evicted_turn_count=snapshot.evicted_turn_count,
            missing_turn_count=snapshot.missing_turn_count,
        )

    def _relevant(
        self,
        active_turn: ActiveConversationTurn,
        candidates: tuple[MemoryEntry, ...],
    ) -> tuple[MemoryEntry, ...]:
        if self._limits.max_relevant_older_turns == 0:
            return ()
        query_terms = set(self._term_extractor.extract(active_turn.text))
        if not query_terms:
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

    def _active_context(
        self,
        active_turn: ActiveConversationTurn,
        *,
        remaining: int,
    ) -> tuple[PredictionContextTurn, int]:
        limit = min(self._limits.max_active_turn_chars, remaining)
        text, truncated = _truncate(active_turn.text, limit)
        return (
            PredictionContextTurn(
                turn_id=active_turn.turn_id,
                turn_sequence=active_turn.turn_sequence,
                source_utterance_ids=active_turn.source_utterance_ids,
                source_transcript_sequences=(
                    active_turn.source_transcript_sequences
                ),
                audio_source=active_turn.audio_source,
                speaker_role=active_turn.speaker_role,
                continuity_quality=active_turn.continuity_quality,
                text=text,
                original_text_chars=len(active_turn.text),
                text_truncated=truncated,
                selection_reason=PredictionContextSelectionReason.ACTIVE_TURN,
            ),
            remaining - len(text),
        )

    def _fit_recent(
        self,
        entries: tuple[MemoryEntry, ...],
        remaining: int,
    ) -> tuple[tuple[PredictionContextTurn, ...], int]:
        selected: list[PredictionContextTurn] = []
        for entry in reversed(entries):
            if remaining <= 0:
                break
            turn, remaining = self._memory_context(
                entry,
                PredictionContextSelectionReason.RECENT_MEMORY,
                remaining=remaining,
            )
            selected.append(turn)
        selected.reverse()
        return tuple(selected), remaining

    def _fit_relevant(
        self,
        entries: tuple[MemoryEntry, ...],
        remaining: int,
    ) -> tuple[tuple[PredictionContextTurn, ...], int]:
        selected: list[PredictionContextTurn] = []
        for entry in entries:
            if remaining <= 0:
                break
            turn, remaining = self._memory_context(
                entry,
                PredictionContextSelectionReason.RELEVANT_OLDER_MEMORY,
                remaining=remaining,
            )
            selected.append(turn)
        selected.sort(key=lambda turn: turn.turn_sequence)
        return tuple(selected), remaining

    def _memory_context(
        self,
        entry: MemoryEntry,
        reason: PredictionContextSelectionReason,
        *,
        remaining: int,
    ) -> tuple[PredictionContextTurn, int]:
        limit = min(self._limits.max_memory_turn_chars, remaining)
        text, additionally_truncated = _truncate(entry.text, limit)
        turn = PredictionContextTurn(
            turn_id=entry.turn_id,
            turn_sequence=entry.turn_sequence,
            source_utterance_ids=entry.source_utterance_ids,
            source_transcript_sequences=entry.source_transcript_sequences,
            audio_source=entry.audio_source,
            speaker_role=entry.speaker_role,
            continuity_quality=entry.continuity_quality,
            text=text,
            original_text_chars=entry.original_text_chars,
            text_truncated=entry.text_truncated or additionally_truncated,
            selection_reason=reason,
        )
        return turn, remaining - len(text)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if limit < 1:
        raise ValueError("prediction context cannot fit the active turn")
    if len(text) <= limit:
        return text, False
    if limit == 1:
        return "…", True
    return f"{text[: limit - 1]}…", True
