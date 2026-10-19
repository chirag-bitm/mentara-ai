import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.stt.base import TranscriptResult
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry


class AudioTriggeredProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.closed = False
        self._results: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()

    async def connect(self) -> None:
        return None

    async def send_audio(self, audio: bytes) -> None:
        await self._results.put(TranscriptResult(self.text, True, True))

    async def finish(self) -> None:
        await self._results.put(None)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while True:
            result = await self._results.get()
            if result is None:
                return
            yield result

    async def close(self) -> None:
        self.closed = True


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        conversation_analysis_enabled=False,
        answer_generation_enabled=False,
    )


def test_browser_reconnect_replays_canonical_state_without_duplicate_identity(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    providers = iter(
        [
            AudioTriggeredProvider("Before browser reconnect."),
            AudioTriggeredProvider("After browser reconnect."),
        ]
    )
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: next(providers),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json({"type": "session.start"})
        session_event = websocket.receive_json()
        assert session_event["type"] == "session.ready"
        assert session_event["resumed"] is False
        assert websocket.receive_json()["status"] == "ready"
        websocket.send_bytes(b"first audio")
        before = websocket.receive_json()
        assert before["type"] == "transcript.final"

    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json(
            {
                "type": "session.resume",
                "resume_token": session_event["resume_token"],
            }
        )
        assert websocket.receive_json()["status"] == "reconnecting"
        resumed_event = websocket.receive_json()
        assert resumed_event["type"] == "session.ready"
        assert resumed_event["resumed"] is True
        assert resumed_event["session_id"] == session_event["session_id"]
        assert resumed_event["resume_token"] == session_event["resume_token"]
        assert websocket.receive_json()["status"] == "degraded"
        replayed = websocket.receive_json()
        assert replayed == before
        assert websocket.receive_json()["status"] == "ready"

        websocket.send_bytes(b"second audio")
        after = websocket.receive_json()
        assert after["type"] == "transcript.final"
        assert after["session_id"] == before["session_id"]
        assert after["utterance_id"] != before["utterance_id"]
        assert after["sequence"] == before["sequence"] + 1

        websocket.send_json({"type": "stop"})
        assert websocket.receive_json()["status"] == "stopping"
        assert websocket.receive_json()["status"] == "stopped"

    assert registry.size == 0


def test_invalid_resume_token_is_rejected_before_provider_creation(monkeypatch) -> None:
    provider_created = False

    def fail_if_called(_settings, lifecycle_callback=None):
        nonlocal provider_created
        provider_created = True
        raise AssertionError("Provider must not be created for an invalid resume token")

    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        InMemoryTranscriptionSessionRegistry(),
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        fail_if_called,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json(
            {"type": "session.resume", "resume_token": "invalid-token"}
        )
        error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "SESSION_RESUME_UNAVAILABLE"
    assert provider_created is False


def test_invalid_first_message_is_rejected_without_provider_quota(monkeypatch) -> None:
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: (_ for _ in ()).throw(
            AssertionError("Provider must not be created before a valid handshake")
        ),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json([])
        error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "INVALID_SESSION_COMMAND"


def test_malformed_post_handshake_commands_do_not_crash_active_session(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    provider = AudioTriggeredProvider("Session remains healthy.")
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: provider,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json({"type": "session.start"})
        assert websocket.receive_json()["type"] == "session.ready"
        assert websocket.receive_json()["status"] == "ready"

        websocket.send_text("not-json")
        websocket.send_json([])
        websocket.send_json({"type": "unknown"})
        websocket.send_bytes(b"audio after malformed commands")

        result = websocket.receive_json()
        assert result["type"] == "transcript.final"
        assert result["text"] == "Session remains healthy."

        websocket.send_json({"type": "stop"})
        assert websocket.receive_json()["status"] == "stopping"
        assert websocket.receive_json()["status"] == "stopped"

    assert provider.closed is True
    assert registry.size == 0
