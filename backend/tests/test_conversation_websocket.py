import asyncio
from collections import deque
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.stt.base import STTProviderFatalError, TranscriptResult
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry


class ControlledProvider:
    def __init__(self, *responses: TranscriptResult | Exception) -> None:
        self._responses = deque(responses)
        self._results: asyncio.Queue[TranscriptResult | Exception | None] = (
            asyncio.Queue()
        )
        self.closed = False

    async def connect(self) -> None:
        return None

    async def send_audio(self, _audio: bytes) -> None:
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


def settings(*, merge_window_ms: int = 0) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        conversation_analysis_enabled=True,
        conversation_turn_merge_window_ms=merge_window_ms,
        answer_generation_enabled=False,
        prediction_enabled=False,
    )


def start(websocket) -> dict[str, object]:
    assert websocket.receive_json()["status"] == "connecting"
    websocket.send_json({"type": "session.start"})
    ready = websocket.receive_json()
    assert ready["type"] == "session.ready"
    assert websocket.receive_json()["status"] == "ready"
    return ready


def stop(websocket) -> None:
    websocket.send_json({"type": "stop"})
    assert websocket.receive_json()["status"] == "stopping"
    assert websocket.receive_json()["status"] == "stopped"


def configure(monkeypatch, registry, provider_factory, *, merge_window_ms=0) -> None:
    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: settings(merge_window_ms=merge_window_ms),
    )
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        registry,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        provider_factory,
    )


def test_question_emits_one_stable_turn_and_detection_event(monkeypatch, caplog) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    provider = ControlledProvider(
        TranscriptResult("Can you explain Redis?", True, True)
    )
    configure(monkeypatch, registry, lambda *_args, **_kwargs: provider)

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        ready = start(websocket)
        websocket.send_bytes(b"question")
        transcript = websocket.receive_json()
        turn = websocket.receive_json()
        detection = websocket.receive_json()

        assert transcript["type"] == "transcript.final"
        assert turn["type"] == "turn.finalized"
        assert turn["session_id"] == ready["session_id"]
        assert turn["source_utterance_ids"] == [transcript["utterance_id"]]
        assert turn["source_transcript_sequences"] == [transcript["sequence"]]
        assert detection["type"] == "question.detected"
        assert detection["source_turn_id"] == turn["turn_id"]
        assert detection["kind"] == "request"
        assert turn["transcript_final_to_turn_ms"] >= 0
        assert detection["turn_to_detection_ms"] >= 0
        stop(websocket)

    assert provider.closed is True
    assert registry.size == 0
    assert "Can you explain Redis?" not in caplog.text


def test_statement_emits_turn_without_question_detection(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    provider = ControlledProvider(
        TranscriptResult("The deployment completed successfully.", True, True)
    )
    configure(monkeypatch, registry, lambda *_args, **_kwargs: provider)

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        start(websocket)
        websocket.send_bytes(b"statement")
        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.finalized"
        stop(websocket)


def test_browser_resume_replays_derived_events_idempotently(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    providers = iter(
        [
            ControlledProvider(TranscriptResult("What is Redis?", True, True)),
            ControlledProvider(),
        ]
    )
    configure(
        monkeypatch,
        registry,
        lambda *_args, **_kwargs: next(providers),
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session = start(websocket)
        websocket.send_bytes(b"question")
        original = [websocket.receive_json() for _ in range(3)]
        assert [event["type"] for event in original] == [
            "transcript.final",
            "turn.finalized",
            "question.detected",
        ]

    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json()["status"] == "connecting"
        websocket.send_json(
            {"type": "session.resume", "resume_token": session["resume_token"]}
        )
        assert websocket.receive_json()["status"] == "reconnecting"
        resumed = websocket.receive_json()
        assert resumed["session_id"] == session["session_id"]
        assert websocket.receive_json()["status"] == "degraded"
        replayed = [websocket.receive_json() for _ in range(3)]
        assert replayed == original
        assert websocket.receive_json()["status"] == "ready"
        stop(websocket)

    assert registry.size == 0


def test_duplicate_provider_final_near_rotation_does_not_redetect(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    provider = ControlledProvider(
        TranscriptResult("Why Redis?", True, True),
        TranscriptResult("Why Redis?", True, True),
    )
    configure(monkeypatch, registry, lambda *_args, **_kwargs: provider)

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        start(websocket)
        websocket.send_bytes(b"first final")
        assert [websocket.receive_json()["type"] for _ in range(3)] == [
            "transcript.final",
            "turn.finalized",
            "question.detected",
        ]
        websocket.send_bytes(b"duplicate final")
        stop(websocket)


def test_stop_flushes_pending_turn_before_stopped(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    provider = ControlledProvider(
        TranscriptResult("Give me an example.", True, True)
    )
    configure(
        monkeypatch,
        registry,
        lambda *_args, **_kwargs: provider,
        merge_window_ms=2_000,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        start(websocket)
        websocket.send_bytes(b"request")
        assert websocket.receive_json()["type"] == "transcript.final"
        websocket.send_json({"type": "stop"})
        assert websocket.receive_json()["status"] == "stopping"
        turn = websocket.receive_json()
        detection = websocket.receive_json()
        assert turn["type"] == "turn.finalized"
        assert turn["finalization_reason"] == "stop_requested"
        assert detection["type"] == "question.detected"
        assert websocket.receive_json()["status"] == "stopped"


def test_fatal_provider_failure_flushes_pending_turn_and_cleans_session(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    provider = ControlledProvider(
        TranscriptResult("What happens if Redis fails?", True, True),
        STTProviderFatalError("quota exhausted"),
    )
    configure(
        monkeypatch,
        registry,
        lambda *_args, **_kwargs: provider,
        merge_window_ms=2_000,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        start(websocket)
        websocket.send_bytes(b"final")
        assert websocket.receive_json()["type"] == "transcript.final"
        websocket.send_bytes(b"fatal")
        turn = websocket.receive_json()
        detection = websocket.receive_json()
        error = websocket.receive_json()
        assert turn["type"] == "turn.finalized"
        assert turn["finalization_reason"] == "provider_failed"
        assert turn["continuity_quality"] == "degraded"
        assert detection["type"] == "question.detected"
        assert error["type"] == "error"

    assert provider.closed is True
    assert registry.size == 0
