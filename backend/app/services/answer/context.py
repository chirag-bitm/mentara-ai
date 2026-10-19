from __future__ import annotations

import logging
from collections.abc import Callable
from time import perf_counter_ns
from typing import Protocol, Sequence

from app.services.answer.models import (
    AnswerContext,
    AnswerContextTurn,
    AnswerRequest,
)
from app.services.conversation.models import ConversationTurn
from app.services.memory.models import MemorySnapshot
from app.services.memory.planner import (
    ContextPlanner,
    DeterministicContextPlanner,
    PlannedContextTurn,
)


logger = logging.getLogger(__name__)


class AnswerContextAssembler(Protocol):
    """Replaceable M5 extension point; providers do not own Mentara memory."""

    def assemble(
        self,
        request: AnswerRequest,
        source_turn: ConversationTurn,
        *,
        recent_finalized_turns: Sequence[ConversationTurn],
    ) -> AnswerContext: ...


class BoundedAnswerContextAssembler:
    def __init__(
        self,
        *,
        max_recent_turns: int = 2,
        max_total_chars: int = 6_000,
        max_turn_chars: int = 2_000,
    ) -> None:
        if max_recent_turns < 0:
            raise ValueError("max_recent_turns must not be negative")
        if max_total_chars < 1 or max_turn_chars < 1:
            raise ValueError("context character limits must be positive")
        self._max_recent_turns = max_recent_turns
        self._max_total_chars = max_total_chars
        self._max_turn_chars = max_turn_chars

    def assemble(
        self,
        request: AnswerRequest,
        source_turn: ConversationTurn,
        *,
        recent_finalized_turns: Sequence[ConversationTurn],
    ) -> AnswerContext:
        if request.session_id != source_turn.session_id:
            raise ValueError("answer request/source turn session mismatch")
        if request.source_turn_id != source_turn.turn_id:
            raise ValueError("answer request does not refer to the source turn")

        source = self._context_turn(
            source_turn,
            limit=min(self._max_turn_chars, self._max_total_chars),
        )
        remaining = self._max_total_chars - len(source.text)
        candidates = [
            turn
            for turn in recent_finalized_turns
            if turn.session_id == request.session_id
            and turn.turn_sequence < source_turn.turn_sequence
        ]
        candidates.sort(key=lambda turn: turn.turn_sequence)
        candidates = candidates[-self._max_recent_turns :] if self._max_recent_turns else []

        selected_reversed: list[AnswerContextTurn] = []
        for turn in reversed(candidates):
            if remaining <= 0:
                break
            context_turn = self._context_turn(
                turn,
                limit=min(self._max_turn_chars, remaining),
            )
            selected_reversed.append(context_turn)
            remaining -= len(context_turn.text)

        recent = tuple(reversed(selected_reversed))
        return AnswerContext(
            session_id=request.session_id,
            answer_id=request.answer_id,
            assistance_kind=request.assistance_kind,
            source_turn=source,
            recent_turns=recent,
            total_text_chars=len(source.text) + sum(len(turn.text) for turn in recent),
        )

    @staticmethod
    def _context_turn(turn: ConversationTurn, *, limit: int) -> AnswerContextTurn:
        text, truncated = _truncate(turn.text, limit)
        return AnswerContextTurn(
            turn_id=turn.turn_id,
            turn_sequence=turn.turn_sequence,
            speaker_role=turn.speaker_role,
            continuity_quality=turn.continuity_quality,
            text=text,
            text_truncated=truncated,
        )


class MemoryAnswerContextAssembler:
    """M5 context adapter backed by an immutable logical-session snapshot."""

    def __init__(
        self,
        *,
        snapshot_provider: Callable[[], MemorySnapshot | None],
        planner: ContextPlanner | None = None,
        fallback: BoundedAnswerContextAssembler | None = None,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._planner = planner or DeterministicContextPlanner()
        self._fallback = fallback or BoundedAnswerContextAssembler()

    def assemble(
        self,
        request: AnswerRequest,
        source_turn: ConversationTurn,
        *,
        recent_finalized_turns: Sequence[ConversationTurn],
    ) -> AnswerContext:
        started_ns = perf_counter_ns()
        snapshot = self._snapshot_provider()
        if snapshot is None or snapshot.session_id != request.session_id:
            return self._fallback_context(
                request,
                source_turn,
                recent_finalized_turns,
                started_ns=started_ns,
                reason="snapshot_unavailable",
            )
        try:
            plan = self._planner.plan(snapshot, source_turn_id=source_turn.turn_id)
            if (
                plan.source_turn.turn_sequence != source_turn.turn_sequence
                or plan.source_turn.turn_id != request.source_turn_id
            ):
                raise ValueError("memory source provenance mismatch")
            context = AnswerContext(
                session_id=request.session_id,
                answer_id=request.answer_id,
                assistance_kind=request.assistance_kind,
                source_turn=self._from_planned(plan.source_turn),
                recent_turns=tuple(
                    self._from_planned(turn) for turn in plan.recent_turns
                ),
                relevant_older_turns=tuple(
                    self._from_planned(turn)
                    for turn in plan.relevant_older_turns
                ),
                total_text_chars=plan.total_text_chars,
                memory_revision=plan.memory_revision,
                memory_continuity=plan.memory_continuity,
                evicted_turn_count=plan.evicted_turn_count,
                missing_turn_count=plan.missing_turn_count,
            )
        except (ValueError, RuntimeError) as exc:
            return self._fallback_context(
                request,
                source_turn,
                recent_finalized_turns,
                started_ns=started_ns,
                reason=type(exc).__name__,
            )

        logger.info(
            "Memory answer context assembled: context_assembly_ms=%s "
            "memory_revision=%s stored_turn_count=%s stored_text_chars=%s "
            "source_topic_term_count=%s older_candidate_count=%s "
            "selected_recent_turn_count=%s selected_relevant_turn_count=%s "
            "context_text_chars=%s",
            _elapsed_ms(started_ns),
            snapshot.memory_revision,
            snapshot.stored_turn_count,
            snapshot.stored_text_chars,
            next(
                (
                    len(entry.topic_terms)
                    for entry in snapshot.entries
                    if entry.turn_id == source_turn.turn_id
                ),
                0,
            ),
            max(
                0,
                sum(
                    entry.turn_sequence < source_turn.turn_sequence
                    for entry in snapshot.entries
                )
                - len(context.recent_turns),
            ),
            len(context.recent_turns),
            len(context.relevant_older_turns),
            context.total_text_chars,
        )
        return context

    def _fallback_context(
        self,
        request: AnswerRequest,
        source_turn: ConversationTurn,
        recent_finalized_turns: Sequence[ConversationTurn],
        *,
        started_ns: int,
        reason: str,
    ) -> AnswerContext:
        context = self._fallback.assemble(
            request,
            source_turn,
            recent_finalized_turns=recent_finalized_turns,
        )
        logger.warning(
            "Memory answer context unavailable; using bounded M4 fallback: "
            "reason=%s context_assembly_ms=%s context_text_chars=%s",
            reason,
            _elapsed_ms(started_ns),
            context.total_text_chars,
        )
        return context

    @staticmethod
    def _from_planned(turn: PlannedContextTurn) -> AnswerContextTurn:
        return AnswerContextTurn(
            turn_id=turn.turn_id,
            turn_sequence=turn.turn_sequence,
            speaker_role=turn.speaker_role,
            continuity_quality=turn.continuity_quality,
            text=turn.text,
            text_truncated=turn.text_truncated,
            provenance=turn.provenance,
        )


def _elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 3)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped, False
    if limit == 1:
        return "…", True
    return f"{stripped[: limit - 1]}…", True
