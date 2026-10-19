from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import (
    ActiveConversationTurn,
    ContinuityQuality,
    ConversationSnapshot,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import CanonicalUtterance


@dataclass(slots=True, frozen=True)
class TurnFinalizationPolicy:
    """Small post-final window for joining provider-split speech segments."""

    merge_window_ms: int = 250

    def __post_init__(self) -> None:
        if self.merge_window_ms < 0:
            raise ValueError("merge_window_ms must not be negative")
        if self.merge_window_ms > 2_000:
            raise ValueError("merge_window_ms must not exceed 2,000 ms")


@dataclass(slots=True, frozen=True)
class TurnEngineUpdate:
    active_turn: ActiveConversationTurn | None
    finalized_turns: tuple[ConversationTurn, ...] = ()
    ignored: bool = False


@dataclass(slots=True)
class _ActiveTurnState:
    turn_id: UUID
    turn_sequence: int
    utterances: list[CanonicalUtterance]
    continuity_quality: ContinuityQuality
    pending_deadline_ms: int | None = None


class ConversationTurnEngine:
    """Pure state machine deriving conversation turns from canonical utterances."""

    def __init__(
        self,
        *,
        session_id: UUID,
        policy: TurnFinalizationPolicy | None = None,
    ) -> None:
        self._session_id = session_id
        self._policy = policy or TurnFinalizationPolicy()
        self._turn_sequence = 0
        self._last_transcript_sequence = 0
        self._active: _ActiveTurnState | None = None
        self._finalized_turns: list[ConversationTurn] = []
        self._finalized_source_ids: set[UUID] = set()

    @property
    def session_id(self) -> UUID:
        return self._session_id

    @property
    def pending_deadline_ms(self) -> int | None:
        return self._active.pending_deadline_ms if self._active is not None else None

    def observe(
        self,
        utterance: CanonicalUtterance,
        *,
        continuity_quality: ContinuityQuality = ContinuityQuality.NORMAL,
    ) -> TurnEngineUpdate:
        if utterance.session_id != self._session_id:
            return TurnEngineUpdate(active_turn=self.active_turn(), ignored=True)
        if utterance.sequence <= self._last_transcript_sequence:
            return TurnEngineUpdate(active_turn=self.active_turn(), ignored=True)

        self._last_transcript_sequence = utterance.sequence
        if utterance.utterance_id in self._finalized_source_ids:
            return TurnEngineUpdate(active_turn=self.active_turn(), ignored=True)

        finalized: list[ConversationTurn] = []
        active = self._active
        if active is not None and self._source_changed(active, utterance):
            completed = self._finalize_active(
                now_ms=max(
                    utterance.first_seen_ms,
                    self._latest_source_finalized_ms(active),
                ),
                reason=TurnFinalizationReason.SOURCE_CHANGED,
            )
            if completed is not None:
                finalized.append(completed)
            else:
                self._active = None
            active = None

        if active is None:
            active = self._start_turn(utterance, continuity_quality)
        else:
            self._merge_utterance(active, utterance)
            if continuity_quality is ContinuityQuality.DEGRADED:
                active.continuity_quality = ContinuityQuality.DEGRADED

        if all(source.is_final for source in active.utterances):
            source_finalized_ms = self._latest_source_finalized_ms(active)
            active.pending_deadline_ms = (
                source_finalized_ms + self._policy.merge_window_ms
            )
        else:
            active.pending_deadline_ms = None

        return TurnEngineUpdate(
            active_turn=self.active_turn(),
            finalized_turns=tuple(finalized),
        )

    def finalize_due(self, *, now_ms: int) -> ConversationTurn | None:
        deadline = self.pending_deadline_ms
        if deadline is None or now_ms < deadline:
            return None
        return self._finalize_active(
            now_ms=now_ms,
            reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        )

    def flush(
        self,
        *,
        now_ms: int,
        reason: TurnFinalizationReason,
    ) -> ConversationTurn | None:
        """Finalize canonical-final content; discard partial-only active state."""

        active = self._active
        if active is None:
            return None
        if not all(utterance.is_final for utterance in active.utterances):
            self._active = None
            return None
        return self._finalize_active(now_ms=now_ms, reason=reason)

    def cancel_active(self) -> bool:
        had_active = self._active is not None
        self._active = None
        return had_active

    def active_turn(self) -> ActiveConversationTurn | None:
        active = self._active
        if active is None:
            return None
        utterances = tuple(active.utterances)
        return ActiveConversationTurn(
            session_id=self._session_id,
            turn_id=active.turn_id,
            turn_sequence=active.turn_sequence,
            source_utterance_ids=tuple(
                utterance.utterance_id for utterance in utterances
            ),
            source_transcript_sequences=tuple(
                utterance.sequence for utterance in utterances
            ),
            audio_source=utterances[0].audio_source,
            speaker_role=utterances[0].speaker_role,
            text=self._joined_text(utterances),
            started_ms=utterances[0].first_seen_ms,
            last_updated_ms=max(
                utterance.last_updated_ms for utterance in utterances
            ),
            continuity_quality=active.continuity_quality,
            awaiting_finalization=active.pending_deadline_ms is not None,
            pending_deadline_ms=active.pending_deadline_ms,
        )

    def snapshot(self) -> ConversationSnapshot:
        return ConversationSnapshot(
            session_id=self._session_id,
            turn_sequence=self._turn_sequence,
            active_turn=self.active_turn(),
            finalized_turns=tuple(self._finalized_turns),
            assistance_detections=(),
        )

    def reset(self, *, session_id: UUID) -> ConversationSnapshot:
        self._session_id = session_id
        self._turn_sequence = 0
        self._last_transcript_sequence = 0
        self._active = None
        self._finalized_turns = []
        self._finalized_source_ids = set()
        return self.snapshot()

    def mark_active_degraded(self) -> None:
        if self._active is not None:
            self._active.continuity_quality = ContinuityQuality.DEGRADED

    def _start_turn(
        self,
        utterance: CanonicalUtterance,
        continuity_quality: ContinuityQuality,
    ) -> _ActiveTurnState:
        self._turn_sequence += 1
        active = _ActiveTurnState(
            turn_id=derive_turn_id(self._session_id, self._turn_sequence),
            turn_sequence=self._turn_sequence,
            utterances=[utterance],
            continuity_quality=continuity_quality,
        )
        self._active = active
        return active

    @staticmethod
    def _source_changed(
        active: _ActiveTurnState,
        utterance: CanonicalUtterance,
    ) -> bool:
        first = active.utterances[0]
        return (
            utterance.audio_source is not first.audio_source
            or utterance.speaker_role is not first.speaker_role
        )

    @staticmethod
    def _merge_utterance(
        active: _ActiveTurnState,
        utterance: CanonicalUtterance,
    ) -> None:
        for index, current in enumerate(active.utterances):
            if current.utterance_id == utterance.utterance_id:
                if current.is_final or utterance.revision <= current.revision:
                    return
                active.utterances[index] = utterance
                return
        active.utterances.append(utterance)

    def _finalize_active(
        self,
        *,
        now_ms: int,
        reason: TurnFinalizationReason,
    ) -> ConversationTurn | None:
        active = self._active
        if active is None or not all(
            utterance.is_final for utterance in active.utterances
        ):
            return None

        utterances = tuple(active.utterances)
        source_finalized_ms = self._latest_source_finalized_ms(active)
        finalized_ms = max(now_ms, source_finalized_ms)
        turn = ConversationTurn(
            session_id=self._session_id,
            turn_id=active.turn_id,
            turn_sequence=active.turn_sequence,
            source_utterance_ids=tuple(
                utterance.utterance_id for utterance in utterances
            ),
            source_transcript_sequences=tuple(
                utterance.sequence for utterance in utterances
            ),
            audio_source=utterances[0].audio_source,
            speaker_role=utterances[0].speaker_role,
            text=self._joined_text(utterances),
            started_ms=utterances[0].first_seen_ms,
            last_updated_ms=max(
                utterance.last_updated_ms for utterance in utterances
            ),
            source_finalized_ms=source_finalized_ms,
            finalized_ms=finalized_ms,
            finalization_reason=reason,
            continuity_quality=active.continuity_quality,
            transcript_final_to_turn_ms=finalized_ms - source_finalized_ms,
        )
        self._finalized_turns.append(turn)
        self._finalized_source_ids.update(turn.source_utterance_ids)
        self._active = None
        return turn

    @staticmethod
    def _latest_source_finalized_ms(active: _ActiveTurnState) -> int:
        values = (
            utterance.finalized_ms
            for utterance in active.utterances
            if utterance.finalized_ms is not None
        )
        return max(values, default=0)

    @staticmethod
    def _joined_text(utterances: tuple[CanonicalUtterance, ...]) -> str:
        return " ".join(utterance.text.strip() for utterance in utterances).strip()
