from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class AudioSource(str, Enum):
    """Where the audio entered Mentara."""

    MICROPHONE = "microphone"
    SYSTEM = "system"


class SpeakerRole(str, Enum):
    """Provider-neutral role of the person represented by an utterance."""

    LOCAL_USER = "local_user"
    REMOTE_SPEAKER = "remote_speaker"


@dataclass(slots=True, frozen=True)
class CanonicalUtterance:
    """Latest canonical state emitted for one spoken utterance."""

    session_id: UUID
    utterance_id: UUID
    sequence: int
    revision: int
    audio_source: AudioSource
    speaker_role: SpeakerRole
    text: str
    is_final: bool
    first_seen_ms: int
    last_updated_ms: int
    finalized_ms: int | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("sequence must start at 1")
        if self.revision < 1:
            raise ValueError("revision must start at 1")
        if not self.text.strip():
            raise ValueError("canonical utterance text must not be empty")
        if self.first_seen_ms < 0:
            raise ValueError("first_seen_ms must not be negative")
        if self.last_updated_ms < self.first_seen_ms:
            raise ValueError("last_updated_ms must not precede first_seen_ms")
        if self.is_final:
            if self.finalized_ms is None:
                raise ValueError("finalized_ms is required for a final utterance")
            if self.finalized_ms < self.last_updated_ms:
                raise ValueError("finalized_ms must not precede last_updated_ms")
        elif self.finalized_ms is not None:
            raise ValueError("a partial utterance cannot have finalized_ms")


@dataclass(slots=True, frozen=True)
class TranscriptSessionSnapshot:
    """Read-only view of the backend-owned transcript state."""

    session_id: UUID
    sequence: int
    active_utterance: CanonicalUtterance | None
    finalized_utterances: tuple[CanonicalUtterance, ...]
