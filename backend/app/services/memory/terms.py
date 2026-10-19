from __future__ import annotations

import re
import unicodedata
from typing import Protocol


class TopicTermExtractor(Protocol):
    def extract(self, text: str) -> tuple[str, ...]: ...


class DeterministicTopicTermExtractor:
    """Small local metadata extractor; terms remain lossy and untrusted."""

    _TOKEN = re.compile(r"[^\W_]+(?:[.+#/-][^\W_]+)*", re.UNICODE)
    _STOP_WORDS = frozenset(
        {
            "about", "again", "also", "and", "are", "back", "because",
            "been", "being", "can", "could", "did", "does", "explain",
            "for", "from", "have", "how", "into", "just", "like", "mean",
            "more", "that", "the", "their", "then", "there", "these",
            "they", "this", "those", "was", "what", "when", "where",
            "which", "why", "will", "with", "would", "you", "your",
        }
    )

    def __init__(self, *, max_terms: int = 24, max_term_chars: int = 64) -> None:
        if max_terms < 0:
            raise ValueError("maximum topic terms must not be negative")
        if max_term_chars < 1 or max_term_chars > 64:
            raise ValueError("topic term character limit must be between 1 and 64")
        self._max_terms = max_terms
        self._max_term_chars = max_term_chars

    def extract(self, text: str) -> tuple[str, ...]:
        if self._max_terms == 0:
            return ()
        normalized_text = unicodedata.normalize("NFKC", text)
        # Format controls such as zero-width joiners are not meaningful topic
        # boundaries. Removing them prevents visually identical provider text
        # from producing different retrieval keys.
        normalized_text = "".join(
            character
            for character in normalized_text
            if unicodedata.category(character) != "Cf"
        )
        terms: list[str] = []
        seen: set[str] = set()
        for match in self._TOKEN.finditer(normalized_text):
            raw = match.group(0)
            normalized = raw.casefold()[: self._max_term_chars]
            distinctive = (
                len(normalized) >= 3
                or any(character.isdigit() for character in normalized)
                or (len(raw) >= 2 and raw.isupper())
            )
            if (
                not distinctive
                or normalized in self._STOP_WORDS
                or normalized in seen
            ):
                continue
            seen.add(normalized)
            terms.append(normalized)
            if len(terms) == self._max_terms:
                break
        return tuple(terms)
