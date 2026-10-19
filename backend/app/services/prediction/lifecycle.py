from dataclasses import replace

from app.services.conversation.models import ContinuityQuality
from app.services.prediction.models import (
    PredictionCandidate,
    PredictionFailure,
    PredictionInvalidationReason,
    PredictionReadiness,
    PredictionSnapshot,
    PredictionState,
    PredictionUsage,
)


class InvalidPredictionTransition(RuntimeError):
    pass


class PredictionLifecycle:
    """Mutable owner that publishes only immutable prediction snapshots."""

    def __init__(self, scheduled: PredictionSnapshot) -> None:
        if scheduled.state is not PredictionState.SCHEDULED:
            raise ValueError("prediction lifecycle must start scheduled")
        self._snapshot = scheduled

    @property
    def snapshot(self) -> PredictionSnapshot:
        return self._snapshot

    def mark_running(
        self,
        *,
        attempt: int,
        at_ms: int,
        context_chars: int,
    ) -> PredictionSnapshot:
        self._require(PredictionState.SCHEDULED)
        self._snapshot = replace(
            self._snapshot,
            attempt=attempt,
            state=PredictionState.RUNNING,
            snapshot_revision=self._snapshot.snapshot_revision + 1,
            provider_started_ms=max(at_ms, self._snapshot.scheduled_ms or at_ms),
            context_chars=context_chars,
        )
        return self._snapshot

    def mark_ready(
        self,
        *,
        candidates: tuple[PredictionCandidate, ...],
        consistent_revision_count: int,
        at_ms: int,
        usage: PredictionUsage | None,
    ) -> PredictionSnapshot:
        self._require(PredictionState.RUNNING)
        readiness = self._readiness(
            candidates=candidates,
            consistent_revision_count=consistent_revision_count,
            awaiting_finalization=self._snapshot.active_turn_awaiting_finalization,
            continuity_quality=self._snapshot.continuity_quality,
        )
        self._snapshot = replace(
            self._snapshot,
            state=PredictionState.READY,
            snapshot_revision=self._snapshot.snapshot_revision + 1,
            candidates=candidates,
            candidate_consistent_revision_count=consistent_revision_count,
            ready_ms=max(at_ms, self._snapshot.provider_started_ms or at_ms),
            readiness=readiness,
            usage=usage,
        )
        return self._snapshot

    def refresh_active_state(
        self,
        *,
        awaiting_finalization: bool,
        continuity_quality: ContinuityQuality,
    ) -> PredictionSnapshot:
        if self._snapshot.state not in {
            PredictionState.SCHEDULED,
            PredictionState.RUNNING,
            PredictionState.READY,
        }:
            raise InvalidPredictionTransition(
                "cannot refresh active state for a terminal prediction"
            )
        readiness = self._snapshot.readiness
        if self._snapshot.state is PredictionState.READY:
            readiness = self._readiness(
                candidates=self._snapshot.candidates,
                consistent_revision_count=(
                    self._snapshot.candidate_consistent_revision_count
                ),
                awaiting_finalization=awaiting_finalization,
                continuity_quality=continuity_quality,
            )
        if (
            awaiting_finalization
            == self._snapshot.active_turn_awaiting_finalization
            and continuity_quality is self._snapshot.continuity_quality
            and readiness is self._snapshot.readiness
        ):
            return self._snapshot
        self._snapshot = replace(
            self._snapshot,
            snapshot_revision=self._snapshot.snapshot_revision + 1,
            active_turn_awaiting_finalization=awaiting_finalization,
            continuity_quality=continuity_quality,
            readiness=readiness,
        )
        return self._snapshot

    def invalidate(
        self,
        reason: PredictionInvalidationReason,
        *,
        at_ms: int,
    ) -> PredictionSnapshot:
        if self._snapshot.state is PredictionState.INVALIDATED:
            return self._snapshot
        self._snapshot = replace(
            self._snapshot,
            state=PredictionState.INVALIDATED,
            snapshot_revision=self._snapshot.snapshot_revision + 1,
            candidates=(),
            candidate_consistent_revision_count=0,
            ready_ms=None,
            terminal_ms=max(at_ms, self._snapshot.input_observed_ms),
            readiness=None,
            invalidation_reason=reason,
            failure=None,
            usage=None,
        )
        return self._snapshot

    def fail(
        self,
        failure: PredictionFailure,
        *,
        at_ms: int,
    ) -> PredictionSnapshot:
        self._require(PredictionState.RUNNING)
        self._snapshot = replace(
            self._snapshot,
            state=PredictionState.FAILED,
            snapshot_revision=self._snapshot.snapshot_revision + 1,
            terminal_ms=max(at_ms, self._snapshot.provider_started_ms or at_ms),
            failure=failure,
        )
        return self._snapshot

    def _require(self, expected: PredictionState) -> None:
        if self._snapshot.state is not expected:
            raise InvalidPredictionTransition(
                f"cannot transition prediction from {self._snapshot.state.value}; "
                f"expected {expected.value}"
            )

    @staticmethod
    def _readiness(
        *,
        candidates: tuple[PredictionCandidate, ...],
        consistent_revision_count: int,
        awaiting_finalization: bool,
        continuity_quality: ContinuityQuality,
    ) -> PredictionReadiness | None:
        if not candidates:
            return None
        if (
            consistent_revision_count >= 2
            and awaiting_finalization
            and continuity_quality is ContinuityQuality.NORMAL
        ):
            return PredictionReadiness.STABLE
        return PredictionReadiness.TENTATIVE
