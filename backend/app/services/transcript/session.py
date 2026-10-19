from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from app.services.stt.base import TranscriptResult
from app.services.transcript.aggregator import TranscriptAggregator
from app.services.transcript.models import (
    CanonicalUtterance,
    TranscriptSessionSnapshot,
)

if TYPE_CHECKING:
    from app.services.answer.models import AnswerSessionSnapshot
    from app.services.answer.runtime import AnswerRuntime
    from app.services.conversation.engine import (
        ConversationTurnEngine,
        TurnFinalizationPolicy,
    )
    from app.services.conversation.models import (
        AssistanceDecision,
        ContinuityQuality,
        ConversationSnapshot,
        ConversationTurn,
    )
    from app.services.memory.memory import ConversationMemory
    from app.services.memory.models import MemoryObservationStatus, MemorySnapshot
    from app.services.prediction.models import (
        PredictionInvalidationReason,
        PredictionSessionSnapshot,
    )
    from app.services.prediction.runtime import PredictionRuntime


class SessionConnectionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass(slots=True, frozen=True)
class TranscriptionSessionSnapshot:
    session_id: UUID
    connection_state: SessionConnectionState
    provider_generation: int
    transcript: TranscriptSessionSnapshot
    conversation: ConversationSnapshot
    answer: AnswerSessionSnapshot | None
    memory: MemorySnapshot | None
    prediction: PredictionSessionSnapshot | None


class TranscriptionSession:
    """Owns canonical state independently of replaceable provider connections."""

    _ALLOWED_TRANSITIONS = {
        SessionConnectionState.CONNECTING: {
            SessionConnectionState.CONNECTED,
            SessionConnectionState.DEGRADED,
            SessionConnectionState.ERROR,
            SessionConnectionState.STOPPED,
        },
        SessionConnectionState.CONNECTED: {
            SessionConnectionState.RECONNECTING,
            SessionConnectionState.DEGRADED,
            SessionConnectionState.ERROR,
            SessionConnectionState.STOPPED,
        },
        SessionConnectionState.RECONNECTING: {
            SessionConnectionState.CONNECTED,
            SessionConnectionState.DEGRADED,
            SessionConnectionState.ERROR,
            SessionConnectionState.STOPPED,
        },
        SessionConnectionState.DEGRADED: {
            SessionConnectionState.CONNECTED,
            SessionConnectionState.RECONNECTING,
            SessionConnectionState.ERROR,
            SessionConnectionState.STOPPED,
        },
        SessionConnectionState.ERROR: {
            SessionConnectionState.RECONNECTING,
            SessionConnectionState.STOPPED,
        },
        SessionConnectionState.STOPPED: set(),
    }

    def __init__(
        self,
        *,
        aggregator: TranscriptAggregator | None = None,
        turn_policy: TurnFinalizationPolicy | None = None,
    ) -> None:
        from app.services.conversation.detector import AssistanceDetectionEngine
        from app.services.conversation.engine import ConversationTurnEngine

        self._aggregator = aggregator or TranscriptAggregator()
        self._turn_engine = ConversationTurnEngine(
            session_id=self._aggregator.session_id,
            policy=turn_policy,
        )
        self._detection_engine = AssistanceDetectionEngine()
        self._answer_runtime: AnswerRuntime | None = None
        self._conversation_memory: ConversationMemory | None = None
        self._prediction_runtime: PredictionRuntime | None = None
        self._connection_state = SessionConnectionState.CONNECTING
        self._provider_generation = 0
        self._continuity_degraded_until_final = False

    @property
    def session_id(self) -> UUID:
        return self._aggregator.session_id

    @property
    def connection_state(self) -> SessionConnectionState:
        return self._connection_state

    @property
    def provider_generation(self) -> int:
        return self._provider_generation

    @property
    def turn_engine(self) -> ConversationTurnEngine:
        return self._turn_engine

    @property
    def answer_runtime(self) -> AnswerRuntime | None:
        return self._answer_runtime

    def attach_answer_runtime(self, runtime: AnswerRuntime) -> None:
        if runtime.snapshot().session_id != self.session_id:
            raise ValueError("answer runtime must belong to the logical session")
        if self._answer_runtime is not None and self._answer_runtime is not runtime:
            raise RuntimeError("logical session already owns an answer runtime")
        self._answer_runtime = runtime

    @property
    def prediction_runtime(self) -> PredictionRuntime | None:
        return self._prediction_runtime

    def attach_prediction_runtime(self, runtime: PredictionRuntime) -> None:
        if runtime.session_id != self.session_id:
            raise ValueError("prediction runtime must belong to the logical session")
        if (
            self._prediction_runtime is not None
            and self._prediction_runtime is not runtime
        ):
            raise RuntimeError("logical session already owns a prediction runtime")
        self._prediction_runtime = runtime

    @property
    def conversation_memory(self) -> ConversationMemory | None:
        return self._conversation_memory

    def attach_conversation_memory(self, memory: ConversationMemory) -> None:
        if memory.session_id != self.session_id:
            raise ValueError("conversation memory must belong to the logical session")
        if (
            self._conversation_memory is not None
            and self._conversation_memory is not memory
        ):
            raise RuntimeError("logical session already owns conversation memory")
        self._conversation_memory = memory

    def observe_memory(
        self,
        turn: ConversationTurn,
    ) -> MemoryObservationStatus | None:
        if self._conversation_memory is None:
            return None
        return self._conversation_memory.observe(turn)

    def memory_snapshot(self) -> MemorySnapshot | None:
        if self._conversation_memory is None:
            return None
        return self._conversation_memory.snapshot()

    @property
    def conversation_continuity_quality(self) -> ContinuityQuality:
        from app.services.conversation.models import ContinuityQuality

        return (
            ContinuityQuality.DEGRADED
            if self._continuity_degraded_until_final
            else ContinuityQuality.NORMAL
        )

    def apply(self, result: TranscriptResult) -> CanonicalUtterance | None:
        return self._aggregator.apply(result)

    def elapsed_ms(self) -> int:
        return self._aggregator.elapsed_ms()

    def mark_continuity_degraded(self) -> None:
        self._continuity_degraded_until_final = True
        self._turn_engine.mark_active_degraded()
        if self._prediction_runtime is not None:
            self._prediction_runtime.mark_continuity_degraded_nowait()

    def acknowledge_conversation_utterance(
        self,
        utterance: CanonicalUtterance,
    ) -> None:
        if utterance.is_final:
            self._continuity_degraded_until_final = False

    def detect_assistance(
        self,
        turn: ConversationTurn,
        *,
        detected_ms: int,
    ) -> AssistanceDecision | None:
        return self._detection_engine.observe(turn, detected_ms=detected_ms)

    def conversation_snapshot(self) -> ConversationSnapshot:
        snapshot = self._turn_engine.snapshot()
        return replace(
            snapshot,
            assistance_detections=self._detection_engine.positive_decisions(),
        )

    def reset(self) -> TranscriptionSessionSnapshot:
        transcript = self._aggregator.reset()
        self._turn_engine.reset(session_id=transcript.session_id)
        self._detection_engine.reset()
        if self._answer_runtime is not None:
            self._answer_runtime.reset(session_id=transcript.session_id)
        if self._conversation_memory is not None:
            self._conversation_memory.reset(session_id=transcript.session_id)
        if self._prediction_runtime is not None:
            self._prediction_runtime.reset(session_id=transcript.session_id)
        self._connection_state = SessionConnectionState.CONNECTING
        self._provider_generation = 0
        self._continuity_degraded_until_final = False
        return self.snapshot()

    def transition(
        self,
        next_state: SessionConnectionState,
    ) -> TranscriptionSessionSnapshot:
        if next_state is self._connection_state:
            return self.snapshot()

        allowed = self._ALLOWED_TRANSITIONS[self._connection_state]
        if next_state not in allowed:
            raise ValueError(
                f"invalid session transition: {self._connection_state.value} "
                f"-> {next_state.value}"
            )

        self._connection_state = next_state
        if next_state is SessionConnectionState.CONNECTED:
            self._provider_generation += 1
        if next_state is SessionConnectionState.STOPPED:
            self._turn_engine.cancel_active()
            if self._answer_runtime is not None:
                self._answer_runtime.shutdown_nowait()
            if self._prediction_runtime is not None:
                from app.services.prediction.models import PredictionInvalidationReason

                self._prediction_runtime.shutdown_nowait(
                    reason=PredictionInvalidationReason.STOP_REQUESTED
                )
            if self._conversation_memory is not None:
                self._conversation_memory.clear()
        return self.snapshot()

    def shutdown_prediction(self, reason: PredictionInvalidationReason) -> None:
        if self._prediction_runtime is not None:
            self._prediction_runtime.shutdown_nowait(reason=reason)

    def snapshot(self) -> TranscriptionSessionSnapshot:
        return TranscriptionSessionSnapshot(
            session_id=self.session_id,
            connection_state=self._connection_state,
            provider_generation=self._provider_generation,
            transcript=self._aggregator.snapshot(),
            conversation=self.conversation_snapshot(),
            answer=(
                self._answer_runtime.snapshot()
                if self._answer_runtime is not None
                else None
            ),
            memory=self.memory_snapshot(),
            prediction=(
                self._prediction_runtime.snapshot()
                if self._prediction_runtime is not None
                else None
            ),
        )
