import asyncio
from collections import deque
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.stt.base import STTProviderFatalError, TranscriptResult
from app.services.stt.rotation import RotatingSTTProvider, RotationPolicy
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry


class ScriptedProvider:
    def __init__(
        self,
        *responses: TranscriptResult | Exception,
        connect_gate: asyncio.Event | None = None,
    ) -> None:
        self._responses = deque(responses)
        self._results: asyncio.Queue[TranscriptResult | Exception | None] = (
            asyncio.Queue()
        )
        self._connect_gate = connect_gate
        self.closed = False

    async def connect(self) -> None:
        if self._connect_gate is not None:
            await self._connect_gate.wait()

    async def send_audio(self, audio: bytes) -> None:
        if self._responses:
            await self._results.put(self._responses.popleft())

    async def finish(self) -> None:
        await self._results.put(None)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while True:
            result = await self._results.get()
            if result is None:
                return
            if isinstance(result, Exception):
                raise result
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


def start_session(websocket) -> dict[str, object]:
    assert websocket.receive_json()["status"] == "connecting"
    websocket.send_json({"type": "session.start"})
    session_event = websocket.receive_json()
    assert session_event["type"] == "session.ready"
    assert websocket.receive_json()["status"] == "ready"
    return session_event


def resume_session(websocket, resume_token: object) -> dict[str, object]:
    assert websocket.receive_json()["status"] == "connecting"
    websocket.send_json(
        {"type": "session.resume", "resume_token": resume_token}
    )
    assert websocket.receive_json()["status"] == "reconnecting"
    session_event = websocket.receive_json()
    assert session_event["type"] == "session.ready"
    assert session_event["resumed"] is True
    assert websocket.receive_json()["status"] == "degraded"
    return session_event


def stop_session(websocket) -> None:
    websocket.send_json({"type": "stop"})
    assert websocket.receive_json()["status"] == "stopping"
    assert websocket.receive_json()["status"] == "stopped"


def test_active_partial_keeps_identity_when_finalized_after_browser_resume(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_provider = ScriptedProvider(
        TranscriptResult("Active wor", is_final=False, speech_final=False)
    )
    resumed_provider = ScriptedProvider(
        TranscriptResult("Active words.", is_final=True, speech_final=True)
    )
    providers = iter([first_provider, resumed_provider])
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: next(providers),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session_event = start_session(websocket)
        websocket.send_bytes(b"partial audio")
        partial = websocket.receive_json()
        assert partial["type"] == "transcript.partial"

    with client.websocket_connect("/ws/transcribe") as websocket:
        resumed_event = resume_session(websocket, session_event["resume_token"])
        replayed = websocket.receive_json()
        assert replayed == partial
        assert websocket.receive_json()["status"] == "ready"

        websocket.send_bytes(b"final audio")
        final = websocket.receive_json()
        assert final["type"] == "transcript.final"
        assert final["session_id"] == resumed_event["session_id"]
        assert final["utterance_id"] == partial["utterance_id"]
        assert final["revision"] == partial["revision"] + 1
        assert final["sequence"] == partial["sequence"] + 1
        stop_session(websocket)

    assert first_provider.closed is True
    assert resumed_provider.closed is True
    assert registry.size == 0


def test_duplicate_final_after_resume_is_suppressed_before_next_utterance(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_provider = ScriptedProvider(
        TranscriptResult("Stable final.", is_final=True, speech_final=True)
    )
    resumed_provider = ScriptedProvider(
        TranscriptResult("Stable final.", is_final=True, speech_final=True),
        TranscriptResult("Next utterance.", is_final=True, speech_final=True),
    )
    providers = iter([first_provider, resumed_provider])
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: next(providers),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session_event = start_session(websocket)
        websocket.send_bytes(b"first audio")
        original = websocket.receive_json()
        assert original["type"] == "transcript.final"

    with client.websocket_connect("/ws/transcribe") as websocket:
        resume_session(websocket, session_event["resume_token"])
        assert websocket.receive_json() == original
        assert websocket.receive_json()["status"] == "ready"

        websocket.send_bytes(b"duplicate provider final")
        websocket.send_bytes(b"new provider final")
        next_final = websocket.receive_json()
        assert next_final["type"] == "transcript.final"
        assert next_final["text"] == "Next utterance."
        assert next_final["utterance_id"] != original["utterance_id"]
        assert next_final["sequence"] == original["sequence"] + 1
        stop_session(websocket)

    assert registry.size == 0


def test_fatal_provider_error_after_resume_closes_and_removes_session(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_provider = ScriptedProvider(
        TranscriptResult("Before fatal error.", is_final=True, speech_final=True)
    )
    resumed_provider = ScriptedProvider(
        STTProviderFatalError("quota exhausted")
    )
    providers = iter([first_provider, resumed_provider])
    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: next(providers),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session_event = start_session(websocket)
        websocket.send_bytes(b"first audio")
        original = websocket.receive_json()
        assert original["type"] == "transcript.final"

    with client.websocket_connect("/ws/transcribe") as websocket:
        resume_session(websocket, session_event["resume_token"])
        assert websocket.receive_json() == original
        assert websocket.receive_json()["status"] == "ready"
        websocket.send_bytes(b"trigger fatal error")
        error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["code"] == "STT_CONNECTION_ERROR"
    assert "quota exhausted" in error["message"]
    assert first_provider.closed is True
    assert resumed_provider.closed is True
    assert registry.size == 0


def test_browser_disconnect_during_rotation_can_resume_canonical_session(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_generation = ScriptedProvider(
        TranscriptResult("Before combined reconnect.", True, True)
    )
    replacement_gate = asyncio.Event()
    blocked_replacement = ScriptedProvider(connect_gate=replacement_gate)
    resumed_provider = ScriptedProvider(
        TranscriptResult("After combined reconnect.", True, True)
    )
    route_provider_calls = 0

    def provider_factory(_settings, lifecycle_callback=None):
        nonlocal route_provider_calls
        route_provider_calls += 1
        if route_provider_calls == 1:
            return RotatingSTTProvider(
                initial_provider=first_generation,
                provider_factory=lambda: blocked_replacement,
                policy=RotationPolicy(
                    rotation_interval_seconds=0.05,
                    final_boundary_wait_seconds=0,
                    audio_buffer_max_chunks=2,
                    reconnect_max_attempts=1,
                    reconnect_base_delay_seconds=0,
                    finish_drain_timeout_seconds=0.2,
                ),
                lifecycle_callback=lifecycle_callback,
            )
        return resumed_provider

    monkeypatch.setattr("app.api.websocket.get_settings", configured_settings)
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider", provider_factory
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session_event = start_session(websocket)
        websocket.send_bytes(b"before rotation")
        original = websocket.receive_json()
        assert original["type"] == "transcript.final"
        assert websocket.receive_json()["status"] == "reconnecting"

    assert first_generation.closed is True
    assert blocked_replacement.closed is True
    assert registry.size == 1

    with client.websocket_connect("/ws/transcribe") as websocket:
        resumed_event = resume_session(websocket, session_event["resume_token"])
        assert resumed_event["session_id"] == session_event["session_id"]
        assert websocket.receive_json() == original
        assert websocket.receive_json()["status"] == "ready"

        websocket.send_bytes(b"after rotation and browser reconnect")
        continued = websocket.receive_json()
        assert continued["type"] == "transcript.final"
        assert continued["text"] == "After combined reconnect."
        assert continued["sequence"] == original["sequence"] + 1
        stop_session(websocket)

    assert resumed_provider.closed is True
    assert registry.size == 0
