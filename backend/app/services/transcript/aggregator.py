from collections.abc import Callable
from dataclasses import replace
from time import monotonic_ns
from uuid import UUID, uuid4

from app.services.stt.base import TranscriptResult
from app.services.transcript.models import (
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
    TranscriptSessionSnapshot,
)


def monotonic_ms() -> int:
    return monotonic_ns() // 1_000_000


class TranscriptAggregator:
    """Converts raw provider results into canonical Mentara utterance state."""

    def __init__(
        self,
        *,
        session_id: UUID | None = None,
        audio_source: AudioSource = AudioSource.MICROPHONE,
        speaker_role: SpeakerRole = SpeakerRole.LOCAL_USER,
        duplicate_window_ms: int = 1_000,
        clock: Callable[[], int] = monotonic_ms,
        session_id_factory: Callable[[], UUID] = uuid4,
        utterance_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if duplicate_window_ms < 0:
            raise ValueError("duplicate_window_ms must not be negative")

        self._audio_source = audio_source
        self._speaker_role = speaker_role
        self._duplicate_window_ms = duplicate_window_ms
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._utterance_id_factory = utterance_id_factory

        self._session_id = session_id or self._session_id_factory()
        self._session_started_at_ms = self._clock()
        self._last_observed_ms = 0
        self._sequence = 0
        self._active_utterance: CanonicalUtterance | None = None
        self._finalized_utterances: list[CanonicalUtterance] = []

    @property
    def session_id(self) -> UUID:
        return self._session_id

    def apply(self, result: TranscriptResult) -> CanonicalUtterance | None:
        """Apply one raw provider result and return an event only for a real change."""

        text = result.text.strip()
        if not text:
            return None

        now_ms = self._now_ms()
        if result.is_final:
            return self._apply_final(text, result.confidence, now_ms)
        return self._apply_partial(text, result.confidence, now_ms)

    def snapshot(self) -> TranscriptSessionSnapshot:
        return TranscriptSessionSnapshot(
            session_id=self._session_id,
            sequence=self._sequence,
            active_utterance=self._active_utterance,
            finalized_utterances=tuple(self._finalized_utterances),
        )

    def elapsed_ms(self) -> int:
        """Return application-observed session time without changing transcript state."""

        return self._now_ms()

    def reset(self, *, session_id: UUID | None = None) -> TranscriptSessionSnapshot:
        """Start a new logical Mentara session without reusing transcript state."""

        self._session_id = session_id or self._session_id_factory()
        self._session_started_at_ms = self._clock()
        self._last_observed_ms = 0
        self._sequence = 0
        self._active_utterance = None
        self._finalized_utterances = []
        return self.snapshot()

    def _apply_partial(
        self,
        text: str,
        confidence: float | None,
        now_ms: int,
    ) -> CanonicalUtterance | None:
        active = self._active_utterance
        if active is None:
            if self._is_recent_exact_duplicate(text, now_ms):
                return None

            active = CanonicalUtterance(
                session_id=self._session_id,
                utterance_id=self._utterance_id_factory(),
                sequence=self._next_sequence(),
                revision=1,
                audio_source=self._audio_source,
                speaker_role=self._speaker_role,
                text=text,
                is_final=False,
                first_seen_ms=now_ms,
                last_updated_ms=now_ms,
                confidence=confidence,
            )
            self._active_utterance = active
            return active

        if text == active.text:
            return None

        updated = replace(
            active,
            sequence=self._next_sequence(),
            revision=active.revision + 1,
            text=text,
            last_updated_ms=now_ms,
            confidence=confidence,
        )
        self._active_utterance = updated
        return updated

    def _apply_final(
        self,
        text: str,
        confidence: float | None,
        now_ms: int,
    ) -> CanonicalUtterance | None:
        active = self._active_utterance
        if active is None:
            if self._is_recent_exact_duplicate(text, now_ms):
                return None

            finalized = CanonicalUtterance(
                session_id=self._session_id,
                utterance_id=self._utterance_id_factory(),
                sequence=self._next_sequence(),
                revision=1,
                audio_source=self._audio_source,
                speaker_role=self._speaker_role,
                text=text,
                is_final=True,
                first_seen_ms=now_ms,
                last_updated_ms=now_ms,
                finalized_ms=now_ms,
                confidence=confidence,
            )
        else:
            finalized = replace(
                active,
                sequence=self._next_sequence(),
                revision=active.revision + 1,
                text=text,
                is_final=True,
                last_updated_ms=now_ms,
                finalized_ms=now_ms,
                confidence=confidence,
            )

        self._active_utterance = None
        self._finalized_utterances.append(finalized)
        return finalized

    def _is_recent_exact_duplicate(self, text: str, now_ms: int) -> bool:
        if not self._finalized_utterances:
            return False

        previous = self._finalized_utterances[-1]
        if previous.text != text or previous.finalized_ms is None:
            return False
        return now_ms - previous.finalized_ms <= self._duplicate_window_ms

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _now_ms(self) -> int:
        observed_ms = self._clock() - self._session_started_at_ms
        self._last_observed_ms = max(self._last_observed_ms, observed_ms, 0)
        return self._last_observed_ms
