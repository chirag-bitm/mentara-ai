from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
import unicodedata

from app.services.conversation.models import ActiveConversationTurn, ContinuityQuality
from app.services.prediction.models import PredictionTriggerReason
from app.services.transcript.models import CanonicalUtterance


@dataclass(slots=True, frozen=True)
class PredictionTriggerPolicyLimits:
    min_active_chars: int = 12
    min_lexical_tokens: int = 3
    long_partial_chars: int = 48
    min_call_interval_ms: int = 1_200

    def __post_init__(self) -> None:
        if self.min_active_chars < 1:
            raise ValueError("prediction minimum active characters must be positive")
        if self.min_lexical_tokens < 1:
            raise ValueError("prediction minimum lexical tokens must be positive")
        if self.long_partial_chars < self.min_active_chars:
            raise ValueError("prediction long-partial threshold is below its minimum")
        if self.min_call_interval_ms < 0:
            raise ValueError("prediction minimum call interval must not be negative")


@dataclass(slots=True, frozen=True)
class PredictionTriggerDecision:
    eligible: bool
    reason: PredictionTriggerReason
    earliest_attempt_ms: int | None = None

    def __post_init__(self) -> None:
        delayed = self.reason is PredictionTriggerReason.MINIMUM_CALL_INTERVAL
        if delayed != (self.earliest_attempt_ms is not None):
            raise ValueError("prediction trigger delay metadata is inconsistent")
        if self.earliest_attempt_ms is not None and not self.eligible:
            raise ValueError("an ineligible prediction cannot have a retry time")


class PredictionTriggerPolicy(Protocol):
    def evaluate(
        self,
        active_turn: ActiveConversationTurn | None,
        triggering_utterance: CanonicalUtterance | None,
        *,
        observed_ms: int,
        last_attempt_started_ms: int | None,
    ) -> PredictionTriggerDecision: ...


class DeterministicPredictionTriggerPolicy:
    """Conservative local eligibility; it predicts no content itself."""

    _LEXICAL_TOKEN = re.compile(r"[^\W_]+(?:[.+#/-][^\W_]+)*", re.UNICODE)
    _BACKCHANNELS = frozenset(
        {
            "absolutely",
            "cool",
            "correct",
            "got it",
            "great",
            "haan",
            "hmm",
            "nice",
            "okay",
            "right",
            "sure",
            "thanks",
            "thank you",
            "theek hai",
            "yeah",
            "yes",
            "yep",
        }
    )
    _SIGNAL_PHRASES = (
        "you mentioned",
        "you said",
        "earlier you",
        "coming back",
        "returning to",
        "what happens",
        "instead of",
        "difference between",
        "walk me through",
        "tell me",
        "can you",
        "could you",
        "would you",
    )
    _SIGNAL_WORDS = frozenset(
        {
            "explain",
            "describe",
            "why",
            "how",
            "what",
            "when",
            "where",
            "which",
            "who",
            "should",
            "kaise",
            "kyun",
            "kyon",
            "kya",
            "batao",
            "samjhao",
            "agar",
        }
    )

    def __init__(
        self,
        *,
        limits: PredictionTriggerPolicyLimits | None = None,
    ) -> None:
        self._limits = limits or PredictionTriggerPolicyLimits()

    @property
    def limits(self) -> PredictionTriggerPolicyLimits:
        return self._limits

    def evaluate(
        self,
        active_turn: ActiveConversationTurn | None,
        triggering_utterance: CanonicalUtterance | None,
        *,
        observed_ms: int,
        last_attempt_started_ms: int | None,
    ) -> PredictionTriggerDecision:
        if observed_ms < 0:
            raise ValueError("prediction trigger observation time cannot be negative")
        if active_turn is None or triggering_utterance is None:
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.NO_ACTIVE_TURN,
            )
        if active_turn.continuity_quality is ContinuityQuality.DEGRADED:
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.CONTINUITY_UNSAFE,
            )

        normalized = _normalize_phrase(active_turn.text)
        lexical_tokens = tuple(self._LEXICAL_TOKEN.findall(normalized))
        compact_chars = sum(character.isalnum() for character in normalized)
        if not normalized:
            return PredictionTriggerDecision(False, PredictionTriggerReason.EMPTY)
        if normalized in self._BACKCHANNELS:
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.BACKCHANNEL,
            )
        if (
            compact_chars < self._limits.min_active_chars
            or len(lexical_tokens) < self._limits.min_lexical_tokens
        ):
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.TOO_SHORT,
            )

        token_set = set(lexical_tokens)
        padded = f" {normalized} "
        has_signal = (
            active_turn.text.rstrip().endswith("?")
            or any(f" {phrase} " in padded for phrase in self._SIGNAL_PHRASES)
            or bool(token_set.intersection(self._SIGNAL_WORDS))
        )
        if active_turn.awaiting_finalization and not has_signal:
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.ORDINARY_STATEMENT,
            )
        if not has_signal and compact_chars < self._limits.long_partial_chars:
            return PredictionTriggerDecision(
                False,
                PredictionTriggerReason.INSUFFICIENT_SIGNAL,
            )

        if last_attempt_started_ms is not None:
            earliest = (
                last_attempt_started_ms + self._limits.min_call_interval_ms
            )
            if observed_ms < earliest:
                return PredictionTriggerDecision(
                    True,
                    PredictionTriggerReason.MINIMUM_CALL_INTERVAL,
                    earliest_attempt_ms=earliest,
                )
        return PredictionTriggerDecision(True, PredictionTriggerReason.ELIGIBLE)


def _normalize_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = " ".join(normalized.split())
    return normalized.strip(" .,!?:;-—")
