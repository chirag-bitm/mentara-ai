import json
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from app.services.stt.base import STTProviderError, TranscriptResult


class DeepgramProvider:
    BASE_URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self, *, api_key: str, model: str, language: str) -> None:
        self._api_key = api_key
        self._model = model
        self._language = language
        self._socket: ClientConnection | None = None

    async def connect(self) -> None:
        query = urlencode(
            {
                "model": self._model,
                "language": self._language,
                "encoding": "linear16",
                "sample_rate": 16000,
                "channels": 1,
                "interim_results": "true",
                "endpointing": 300,
                "utterance_end_ms": 1000,
                "vad_events": "true",
                "punctuate": "true",
                "smart_format": "true",
            }
        )
        self._socket = await connect(
            f"{self.BASE_URL}?{query}",
            additional_headers={"Authorization": f"Token {self._api_key}"},
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**20,
        )

    async def send_audio(self, audio: bytes) -> None:
        if self._socket is None:
            raise STTProviderError("Deepgram connection is not open.")
        await self._socket.send(audio)

    async def finish(self) -> None:
        if self._socket is not None:
            await self._socket.send(json.dumps({"type": "CloseStream"}))

    async def results(self) -> AsyncIterator[TranscriptResult]:
        if self._socket is None:
            raise STTProviderError("Deepgram connection is not open.")

        async for raw_message in self._socket:
            if not isinstance(raw_message, str):
                continue

            payload: dict[str, Any] = json.loads(raw_message)
            message_type = payload.get("type")

            if message_type == "Error":
                detail = payload.get("description") or payload.get("message") or "Unknown provider error"
                raise STTProviderError(str(detail))

            if message_type != "Results":
                continue

            alternatives = payload.get("channel", {}).get("alternatives", [])
            if not alternatives:
                continue

            alternative = alternatives[0]
            transcript = str(alternative.get("transcript", "")).strip()
            if not transcript:
                continue

            confidence_value = alternative.get("confidence")
            confidence = float(confidence_value) if confidence_value is not None else None
            yield TranscriptResult(
                text=transcript,
                is_final=bool(payload.get("is_final", False)),
                speech_final=bool(payload.get("speech_final", False)),
                confidence=confidence,
            )

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None


# Backward-compatible name for any earlier imports; Gemini is the active provider.
DeepgramStreamingClient = DeepgramProvider
