from __future__ import annotations

import re
from typing import Protocol

from app.services.conversation.identity import derive_assistance_detection_id
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ConversationTurn,
)


class AssistanceDetector(Protocol):
    """Replaceable boundary for deciding whether a finalized turn needs help."""

    def detect(
        self,
        turn: ConversationTurn,
        *,
        detected_ms: int,
    ) -> AssistanceDecision: ...


class LocalHeuristicAssistanceDetector:
    """Deterministic English/Hinglish cues with explicit backchannel suppression."""

    _BACKCHANNELS = {
        "acha",
        "accha",
        "alright",
        "correct",
        "fine",
        "got it",
        "haan",
        "han",
        "hmm",
        "ji",
        "okay",
        "ok",
        "right",
        "sure",
        "thank you",
        "thanks",
        "thik hai",
        "understood",
        "yeah",
        "yes",
        "yup",
        "अच्छा",
        "ठीक है",
        "हाँ",
    }
    _INTERROGATIVES = {
        "how",
        "kahan",
        "kahaan",
        "kab",
        "kaise",
        "kaun",
        "kya",
        "kyon",
        "kyun",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "कब",
        "कहाँ",
        "कैसे",
        "कौन",
        "क्या",
        "क्यों",
    }
    _AUXILIARIES = {
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "had",
        "has",
        "have",
        "is",
        "may",
        "might",
        "should",
        "was",
        "were",
        "will",
        "would",
    }
    _QUESTION_SUBJECTS = {
        "he",
        "i",
        "it",
        "redis",
        "she",
        "that",
        "the",
        "they",
        "this",
        "we",
        "you",
    }
    _REQUEST_PREFIXES = (
        "analyze ",
        "answer ",
        "bata sakte ",
        "batao ",
        "calculate ",
        "can you explain ",
        "check ",
        "clarify ",
        "compare ",
        "could you elaborate",
        "create ",
        "define ",
        "describe ",
        "discuss ",
        "draft ",
        "evaluate ",
        "explain ",
        "explain karo ",
        "find ",
        "fix ",
        "generate ",
        "give ",
        "help me ",
        "identify ",
        "list ",
        "name ",
        "outline ",
        "prepare ",
        "provide ",
        "recommend ",
        "review ",
        "rewrite ",
        "samjhao ",
        "show me ",
        "solve ",
        "suppose ",
        "suggest ",
        "summarize ",
        "tell me ",
        "translate ",
        "walk me through ",
        "write ",
        "बताओ ",
        "समझाओ ",
    )
    _POLITE_PREFIXES = ("kindly ", "please ")
    _FOLLOW_UPS = {
        "and then",
        "how so",
        "what else",
        "what next",
        "why not",
    }
    _HINGLISH_QUESTION_ENDINGS = {
        "bataoge",
        "batao",
        "hoga",
        "hogi",
        "honge",
        "karoge",
        "karenge",
        "बताओगे",
        "होगा",
        "होगी",
        "करोगे",
        "करेंगे",
    }

    def detect(
        self,
        turn: ConversationTurn,
        *,
        detected_ms: int,
    ) -> AssistanceDecision:
        if detected_ms < turn.finalized_ms:
            raise ValueError("detection cannot precede turn finalization")

        normalized = self._normalize(turn.text)
        tokens = self._tokens(normalized)
        should_assist = False
        kind = AssistanceKind.NONE
        reason = "no_actionable_cue"

        if normalized in self._BACKCHANNELS:
            reason = "backchannel"
        elif normalized in self._FOLLOW_UPS:
            should_assist = True
            kind = AssistanceKind.QUESTION
            reason = "follow_up"
        elif self._has_request_cue(normalized):
            should_assist = True
            kind = AssistanceKind.REQUEST
            reason = "request_cue"
        elif self._has_interrogative_sentence(normalized):
            should_assist = True
            kind = AssistanceKind.QUESTION
            reason = "interrogative_cue"
        elif self._has_auxiliary_question(normalized):
            should_assist = True
            kind = AssistanceKind.QUESTION
            reason = "auxiliary_question"
        elif (
            any(token in self._INTERROGATIVES for token in tokens)
            and any(token in self._HINGLISH_QUESTION_ENDINGS for token in tokens)
        ):
            should_assist = True
            kind = AssistanceKind.QUESTION
            reason = "hinglish_question_cue"
        elif turn.text.rstrip().endswith("?") and len(tokens) >= 2:
            should_assist = True
            kind = AssistanceKind.QUESTION
            reason = "question_punctuation"
        elif len(tokens) < 2:
            reason = "too_short"

        return AssistanceDecision(
            detection_id=derive_assistance_detection_id(turn.turn_id),
            session_id=turn.session_id,
            source_turn_id=turn.turn_id,
            source_turn_sequence=turn.turn_sequence,
            should_assist=should_assist,
            kind=kind,
            detected_ms=detected_ms,
            turn_to_detection_ms=detected_ms - turn.finalized_ms,
            reason=reason,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = text.casefold().strip()
        without_edge_punctuation = re.sub(r"^[\W_]+|[\W_]+$", "", lowered)
        return re.sub(r"\s+", " ", without_edge_punctuation)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, flags=re.UNICODE)

    @classmethod
    def _has_request_cue(cls, text: str) -> bool:
        sentence_starts = re.split(r"[.!?]+\s*", text)
        return any(
            core == prefix.strip() or core.startswith(prefix)
            for sentence in sentence_starts
            if sentence
            for core in (cls._without_polite_prefix(sentence),)
            for prefix in cls._REQUEST_PREFIXES
        )

    @classmethod
    def _without_polite_prefix(cls, sentence: str) -> str:
        for prefix in cls._POLITE_PREFIXES:
            if sentence.startswith(prefix):
                return sentence.removeprefix(prefix).lstrip()
        return sentence

    @classmethod
    def _has_interrogative_sentence(cls, text: str) -> bool:
        return any(
            tokens[0] in cls._INTERROGATIVES
            for sentence in re.split(r"[.!?]+\s*", text)
            if (tokens := cls._tokens(cls._without_polite_prefix(sentence)))
        )

    @classmethod
    def _has_auxiliary_question(cls, text: str) -> bool:
        return any(
            len(tokens) >= 2
            and tokens[0] in cls._AUXILIARIES
            and tokens[1] in cls._QUESTION_SUBJECTS
            for sentence in re.split(r"[.!?]+\s*", text)
            if (tokens := cls._tokens(cls._without_polite_prefix(sentence)))
        )


class AssistanceDetectionEngine:
    """Applies a detector once per immutable turn and retains replay state."""

    def __init__(self, detector: AssistanceDetector | None = None) -> None:
        self._detector = detector or LocalHeuristicAssistanceDetector()
        self._processed_turn_ids = set()
        self._positive_decisions: list[AssistanceDecision] = []

    def observe(
        self,
        turn: ConversationTurn,
        *,
        detected_ms: int,
    ) -> AssistanceDecision | None:
        if turn.turn_id in self._processed_turn_ids:
            return None
        decision = self._detector.detect(turn, detected_ms=detected_ms)
        self._processed_turn_ids.add(turn.turn_id)
        if decision.should_assist:
            self._positive_decisions.append(decision)
        return decision

    def positive_decisions(self) -> tuple[AssistanceDecision, ...]:
        return tuple(self._positive_decisions)

    def reset(self) -> None:
        self._processed_turn_ids.clear()
        self._positive_decisions.clear()
