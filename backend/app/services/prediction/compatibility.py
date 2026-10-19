from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.services.memory.terms import DeterministicTopicTermExtractor
from app.services.prediction.identity import normalize_prediction_input_text


class PredictionInputCompatibilityPolicy(Protocol):
    """Decide whether an append-only partial is still the same prediction input."""

    def allows_extension(self, basis_text: str, current_text: str) -> bool: ...


@dataclass(slots=True, frozen=True)
class PredictionInputCompatibilityLimits:
    max_extension_chars: int = 0

    def __post_init__(self) -> None:
        if self.max_extension_chars < 0:
            raise ValueError("compatible extension limit must not be negative")


class ConservativeAppendOnlyPredictionCompatibilityPolicy:
    """Permit only bounded lexical continuations of an unfinished preface.

    This is an operational compatibility rule, not semantic similarity.  It is
    intentionally narrow: the newer input must retain the complete earlier
    lexical prefix (apart from cosmetic punctuation or completion of its last
    token). Unknown topic terms, direct intent, corrections, pivots and strong
    sentence boundaries all fail closed and require a new input revision.
    """

    _BOUNDARY = re.compile(r"[.!?;:]")
    _TOKEN = re.compile(r"[^\W_]+(?:[.+#/-][^\W_]+)*", re.UNICODE)
    _UNSAFE_PHRASES = (
        "actually",
        "but",
        "correction",
        "different topic",
        "didn't",
        "didnt",
        "don't",
        "dont",
        "forget that",
        "however",
        "i mean",
        "instead",
        "never mind",
        "nevermind",
        "no",
        "not",
        "rather",
        "sorry",
    )
    _DIRECT_INTENT_PHRASES = (
        "agar",
        "batao",
        "can you",
        "could you",
        "difference between",
        "explain",
        "how",
        "kaise",
        "kya",
        "kyon",
        "kyun",
        "samjhao",
        "should",
        "tell me",
        "walk me through",
        "what",
        "what happens",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would you",
    )
    _GENERAL_FRAMING_TERMS = frozenset(
        {
            "and",
            "approach",
            "architecture",
            "background",
            "context",
            "decision",
            "decisions",
            "design",
            "detail",
            "details",
            "discussion",
            "earlier",
            "especially",
            "experience",
            "general",
            "generally",
            "implementation",
            "interested",
            "mention",
            "mentioned",
            "particularly",
            "project",
            "reason",
            "reasons",
            "regarding",
            "specific",
            "specifically",
            "system",
            "trade",
            "tradeoff",
            "tradeoffs",
            "understand",
            "understanding",
            "want",
        }
    )

    def __init__(
        self,
        *,
        limits: PredictionInputCompatibilityLimits | None = None,
    ) -> None:
        self._limits = limits or PredictionInputCompatibilityLimits()
        self._terms = DeterministicTopicTermExtractor(max_terms=64)

    def allows_extension(self, basis_text: str, current_text: str) -> bool:
        limit = self._limits.max_extension_chars
        if limit == 0:
            return False

        basis = normalize_prediction_input_text(basis_text)
        current = normalize_prediction_input_text(current_text)
        if not basis or not current:
            return False
        if self._has_strong_boundary(basis) or self._has_strong_boundary(current):
            return False
        if self._contains_phrase(basis, self._UNSAFE_PHRASES) or self._contains_phrase(
            current,
            self._UNSAFE_PHRASES,
        ):
            return False
        if self._contains_phrase(
            basis,
            self._DIRECT_INTENT_PHRASES,
        ) or self._contains_phrase(current, self._DIRECT_INTENT_PHRASES):
            return False
        if self._ends_with_intent_prefix(current):
            return False

        basis_tokens = self._comparison_tokens(basis)
        current_tokens = self._comparison_tokens(current)
        if not basis_tokens or len(current_tokens) < len(basis_tokens):
            return False
        if not self._retains_lexical_prefix(basis_tokens, current_tokens):
            return False

        basis_compact = " ".join(basis_tokens)
        current_compact = " ".join(current_tokens)
        added_chars = max(
            abs(len(current) - len(basis)),
            max(0, len(current_compact) - len(basis_compact)),
        )
        if added_chars > limit:
            return False
        if self._introduces_named_token(basis_text, current_text):
            return False

        basis_terms = {
            self._canonical_term(term) for term in self._terms.extract(basis)
        }
        current_terms = {
            self._canonical_term(term) for term in self._terms.extract(current)
        }
        new_terms = current_terms - basis_terms
        return new_terms <= self._GENERAL_FRAMING_TERMS

    def _has_strong_boundary(self, text: str) -> bool:
        """Allow one cosmetic terminal statement period, but no topic boundary.

        Live STT commonly adds a final period when it marks the same utterance
        provider-final. A single trailing period carries no new lexical input.
        Periods inside the text, ellipses, questions and every other strong
        boundary still fail closed.
        """

        stripped = text.rstrip()
        if stripped.endswith("."):
            stripped = stripped[:-1]
        return self._BOUNDARY.search(stripped) is not None

    @staticmethod
    def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None
            for phrase in phrases
        )

    def _ends_with_intent_prefix(self, suffix: str) -> bool:
        tail = suffix.rsplit(" ", maxsplit=1)[-1]
        if len(tail) < 2:
            return False
        intent_words = {
            phrase.split(" ", maxsplit=1)[0]
            for phrase in self._DIRECT_INTENT_PHRASES
        }
        return any(word.startswith(tail) for word in intent_words)

    def _comparison_tokens(self, text: str) -> tuple[str, ...]:
        return tuple(
            self._canonical_term(token)
            for token in self._TOKEN.findall(text)
            if self._canonical_term(token)
        )

    @staticmethod
    def _canonical_term(term: str) -> str:
        # Hyphenation and apostrophe rendering commonly change between live
        # STT partials. They are cosmetic only inside an otherwise identical
        # lexical token; all other punctuation remains meaningful.
        return term.casefold().replace("-", "").replace("'", "").replace("’", "")

    @staticmethod
    def _retains_lexical_prefix(
        basis_tokens: tuple[str, ...],
        current_tokens: tuple[str, ...],
    ) -> bool:
        if len(current_tokens) < len(basis_tokens):
            return False
        for index, basis_token in enumerate(basis_tokens):
            current_token = current_tokens[index]
            if current_token == basis_token:
                continue
            # Gemini Live may replace a still-evolving neutral framing word
            # with its completed inflection, e.g. `mention` -> `mentioned`.
            # This exception is deliberately limited to allowlisted framing
            # terms with a long common stem; topic anchors remain exact.
            if (
                basis_token
                in ConservativeAppendOnlyPredictionCompatibilityPolicy._GENERAL_FRAMING_TERMS
                and current_token
                in ConservativeAppendOnlyPredictionCompatibilityPolicy._GENERAL_FRAMING_TERMS
                and min(len(basis_token), len(current_token)) >= 5
                and (
                    basis_token.startswith(current_token)
                    or current_token.startswith(basis_token)
                )
            ):
                continue
            # A streaming recognizer may extend only the final unfinished
            # token, for example `trade` -> `trade-offs`.
            if (
                index == len(basis_tokens) - 1
                and len(basis_token) >= 3
                and current_token.startswith(basis_token)
            ):
                continue
            return False
        return True

    def _introduces_named_token(self, basis_text: str, current_text: str) -> bool:
        basis_tokens = {token.casefold() for token in self._TOKEN.findall(basis_text)}
        for token in self._TOKEN.findall(current_text):
            if token.casefold() in basis_tokens:
                continue
            if (len(token) >= 2 and token.isupper()) or any(
                character.isupper() for character in token[1:]
            ):
                return True
        return False
