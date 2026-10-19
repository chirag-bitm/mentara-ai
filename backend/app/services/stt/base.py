from dataclasses import dataclass
from typing import AsyncIterator, Protocol


class STTProviderError(RuntimeError):
    """Raised when a streaming STT provider rejects or ends a session."""


class STTProviderConfigurationError(STTProviderError):
    """Raised when the selected STT provider is unavailable or misconfigured."""


class STTProviderTransientError(STTProviderError):
    """Raised when reconnecting may safely recover the provider connection."""


class STTProviderFatalError(STTProviderError):
    """Raised when retrying would waste time or quota without fixing the cause."""


@dataclass(slots=True, frozen=True)
class TranscriptResult:
    text: str
    is_final: bool
    speech_final: bool
    confidence: float | None = None


class STTProvider(Protocol):
    """Provider-neutral contract used by the browser WebSocket coordinator."""

    async def connect(self) -> None: ...

    async def send_audio(self, audio: bytes) -> None: ...

    async def finish(self) -> None: ...

    def results(self) -> AsyncIterator[TranscriptResult]: ...

    async def close(self) -> None: ...
