import base64
import json
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from app.services.stt.base import (
    STTProviderError,
    STTProviderFatalError,
    STTProviderTransientError,
    TranscriptResult,
)


class GeminiTranscribeProvider:
    """Gemini 3.5 Transcribe Live adapter for raw PCM16 microphone audio."""

    BASE_URL = (
        "wss://generativelanguage.googleapis.com/ws/"
        "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    )

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        language_codes: list[str],
        transcription_mode: str,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language_codes = language_codes
        self._transcription_mode = transcription_mode
        self._socket: ClientConnection | None = None

    async def connect(self) -> None:
        endpoint = f"{self.BASE_URL}?{urlencode({'key': self._api_key})}"
        try:
            self._socket = await connect(
                endpoint,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=2**20,
            )
            await self._socket.send(json.dumps(self._setup_message()))
            raw_message = await self._socket.recv()
            payload = self._parse_message(raw_message)
            self._raise_for_error(payload)
            if "setupComplete" not in payload:
                raise STTProviderError(
                    "Gemini did not confirm the Live Transcription session setup."
                )
        except STTProviderError:
            await self.close()
            raise
        except Exception as exc:
            await self.close()
            raise STTProviderTransientError(self._safe_error_message(exc)) from exc

    def _setup_message(self) -> dict[str, Any]:
        return {
            "setup": {
                "model": f"models/{self._model}",
                "generationConfig": {"responseModalities": ["TEXT"]},
                "inputAudioTranscription": {
                    "languageCodes": self._language_codes,
                    "mode": self._transcription_mode,
                },
            }
        }

    async def send_audio(self, audio: bytes) -> None:
        if self._socket is None:
            raise STTProviderError("Gemini connection is not open.")

        encoded_audio = base64.b64encode(audio).decode("ascii")
        message = {
            "realtimeInput": {
                "audio": {
                    "data": encoded_audio,
                    "mimeType": "audio/pcm;rate=16000",
                }
            }
        }
        try:
            await self._socket.send(json.dumps(message))
        except ConnectionClosed as exc:
            raise STTProviderTransientError(self._safe_error_message(exc)) from exc

    async def finish(self) -> None:
        if self._socket is None:
            return
        try:
            await self._socket.send(
                json.dumps({"realtimeInput": {"audioStreamEnd": True}})
            )
        except ConnectionClosed as exc:
            raise STTProviderTransientError(self._safe_error_message(exc)) from exc

    async def results(self) -> AsyncIterator[TranscriptResult]:
        if self._socket is None:
            raise STTProviderError("Gemini connection is not open.")

        try:
            async for raw_message in self._socket:
                payload = self._parse_message(raw_message)
                self._raise_for_error(payload)
                server_content = payload.get("serverContent")
                if not isinstance(server_content, dict):
                    continue

                interim = server_content.get("interimInputTranscription")
                interim_text = self._transcript_text(interim)
                if interim_text:
                    yield TranscriptResult(
                        text=interim_text,
                        is_final=False,
                        speech_final=False,
                    )

                final = server_content.get("inputTranscription")
                final_text = self._transcript_text(final)
                if final_text:
                    yield TranscriptResult(
                        text=final_text,
                        is_final=True,
                        speech_final=True,
                    )
        except STTProviderError:
            raise
        except ConnectionClosed as exc:
            if exc.code != 1000:
                raise STTProviderTransientError(
                    self._safe_error_message(exc)
                ) from exc

    @staticmethod
    def _parse_message(raw_message: str | bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_message)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise STTProviderError("Gemini returned an invalid JSON message.") from exc
        if not isinstance(payload, dict):
            raise STTProviderError("Gemini returned an unexpected message shape.")
        return payload

    @staticmethod
    def _transcript_text(value: object) -> str:
        if not isinstance(value, dict):
            return ""
        return str(value.get("text", "")).strip()

    @staticmethod
    def _raise_for_error(payload: dict[str, Any]) -> None:
        error = payload.get("error")
        if not isinstance(error, dict):
            return
        message = error.get("message") or "Gemini rejected the transcription session."
        code = error.get("code")
        prefix = f"Gemini error {code}: " if code is not None else "Gemini error: "
        error_type = (
            STTProviderTransientError
            if isinstance(code, int) and code >= 500
            else STTProviderFatalError
        )
        raise error_type(f"{prefix}{message}")

    def _safe_error_message(self, exc: Exception) -> str:
        message = str(exc).replace(self._api_key, "[REDACTED]")
        return f"Gemini Live connection failed: {message}"

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None
