import asyncio
import json

import pytest

from app.services.stt.base import (
    STTProviderError,
    STTProviderFatalError,
    STTProviderTransientError,
    TranscriptResult,
)
from app.services.stt.gemini import GeminiTranscribeProvider


class FakeSocket:
    def __init__(self, messages: list[dict[str, object] | str]) -> None:
        self._messages = [
            message if isinstance(message, str) else json.dumps(message)
            for message in messages
        ]

    def __aiter__(self) -> "FakeSocket":
        return self

    async def __anext__(self) -> str:
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def make_provider() -> GeminiTranscribeProvider:
    return GeminiTranscribeProvider(
        api_key="test-key",
        model="gemini-3.5-transcribe-live",
        language_codes=[],
        transcription_mode="VERBATIM",
    )


def test_maps_interim_and_final_transcripts() -> None:
    provider = make_provider()
    provider._socket = FakeSocket(  # type: ignore[assignment]
        [
            {
                "serverContent": {
                    "interimInputTranscription": {"text": "Hello Men"}
                }
            },
            {
                "serverContent": {
                    "inputTranscription": {"text": "Hello Mentara."}
                }
            },
        ]
    )

    async def collect_results() -> list[TranscriptResult]:
        return [result async for result in provider.results()]

    results = asyncio.run(collect_results())
    assert [result.text for result in results] == ["Hello Men", "Hello Mentara."]
    assert [result.is_final for result in results] == [False, True]
    assert results[1].speech_final is True


def test_provider_error_event_is_raised() -> None:
    provider = make_provider()
    provider._socket = FakeSocket(  # type: ignore[assignment]
        [{"error": {"code": 429, "message": "Quota exceeded"}}]
    )

    async def collect_results() -> list[TranscriptResult]:
        return [result async for result in provider.results()]

    with pytest.raises(STTProviderFatalError, match="Quota exceeded"):
        asyncio.run(collect_results())


def test_server_failure_is_retryable() -> None:
    provider = make_provider()
    provider._socket = FakeSocket(  # type: ignore[assignment]
        [{"error": {"code": 503, "message": "Temporarily unavailable"}}]
    )

    async def collect_results() -> list[TranscriptResult]:
        return [result async for result in provider.results()]

    with pytest.raises(STTProviderTransientError, match="Temporarily unavailable"):
        asyncio.run(collect_results())


@pytest.mark.parametrize(
    ("raw_message", "expected_message"),
    [
        ("not-json", "invalid JSON"),
        (json.dumps([]), "unexpected message shape"),
    ],
)
def test_malformed_provider_message_is_a_safe_terminal_error(
    raw_message: str,
    expected_message: str,
) -> None:
    provider = make_provider()
    provider._socket = FakeSocket([raw_message])  # type: ignore[assignment]

    async def collect_results() -> list[TranscriptResult]:
        return [result async for result in provider.results()]

    with pytest.raises(STTProviderError, match=expected_message):
        asyncio.run(collect_results())
