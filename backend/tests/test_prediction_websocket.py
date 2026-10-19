import asyncio
from collections import deque
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.models import (
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
)
from app.services.prediction import (
    FakePredictionProvider,
    FakePredictionScript,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionProviderError,
    PredictionProviderResult,
)
from app.services.stt.base import TranscriptResult
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry


class ControlledSTTProvider:
    def __init__(self, *responses: TranscriptResult) -> None:
        self._responses = deque(responses)
        self._results: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
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
            yield result

    async def close(self) -> None:
        self.closed = True


def _result(text: str, anchor: str) -> PredictionProviderResult:
    return PredictionProviderResult(
        candidates=(
            PredictionCandidate(
                kind=PredictionCandidateKind.QUESTION,
                text=text,
                anchor_terms=(anchor,),
            ),
        )
    )


def _settings(
    *,
    prediction_enabled: bool = True,
    answer_enabled: bool = False,
) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        answer_generation_enabled=answer_enabled,
        prediction_enabled=prediction_enabled,
        conversation_turn_merge_window_ms=0,
        prediction_coalesce_ms=0,
        prediction_min_call_interval_ms=0,
        prediction_cancelled_attempt_cooldown_ms=0,
        prediction_max_attempts_per_turn=2,
        prediction_max_calls_per_session=2,
    )


def _start(websocket) -> dict[str, object]:
    assert websocket.receive_json()["status"] == "connecting"
    websocket.send_json({"type": "session.start"})
    session = websocket.receive_json()
    assert session["type"] == "session.ready"
    assert websocket.receive_json()["status"] == "ready"
    return session


def _receive_until(websocket, predicate, *, limit: int = 12):
    seen = []
    for _ in range(limit):
        event = websocket.receive_json()
        seen.append(event)
        if predicate(event):
            return event, seen
    raise AssertionError(f"expected event not found; saw {[item['type'] for item in seen]}")


def test_evolving_canonical_turn_emits_latest_revision_only_and_real_turn_wins(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("You mentioned Redis in your architecture", False, False),
        TranscriptResult("You mentioned DynamoDB in your architecture", False, False),
        TranscriptResult("Why did you choose DynamoDB?", True, True),
    )
    predictor = FakePredictionProvider(
        [
            FakePredictionScript(result=_result("Why Redis?", "redis")),
            FakePredictionScript(result=_result("Why DynamoDB?", "dynamodb")),
        ]
    )
    monkeypatch.setattr("app.api.websocket.get_settings", lambda: _settings())
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        registry,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: stt,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_prediction_provider",
        lambda _settings: predictor,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        session = _start(websocket)

        websocket.send_bytes(b"first-prefix")
        first, first_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "prediction.snapshot"
            and event.get("state") == "ready",
        )
        assert first["session_id"] == session["session_id"]
        assert first["input_revision"] == 1
        assert first["candidates"][0]["text"] == "Why Redis?"
        assert first["readiness"] == "tentative"
        assert any(event["type"] == "transcript.partial" for event in first_seen)

        websocket.send_bytes(b"corrected-prefix")
        second, second_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "prediction.snapshot"
            and event.get("state") == "ready"
            and event.get("input_revision") == 2,
        )
        assert second["prediction_id"] == first["prediction_id"]
        assert second["candidates"][0]["text"] == "Why DynamoDB?"
        assert all(
            event.get("input_revision", 2) >= 2
            for event in second_seen
            if event.get("type") == "prediction.snapshot"
        )

        websocket.send_bytes(b"final-question")
        turn, final_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "turn.finalized",
        )
        assert turn["text"] == "Why did you choose DynamoDB?"
        assert any(event["type"] == "transcript.final" for event in final_seen)
        assert len(predictor.requests) == 2
        assert predictor.max_active_call_count == 1

        websocket.send_json({"type": "stop"})
        stopped, _ = _receive_until(
            websocket,
            lambda event: event.get("type") == "status"
            and event.get("status") == "stopped",
        )
        assert stopped["status"] == "stopped"

    assert stt.closed is True
    assert registry.size == 0


def test_prediction_disabled_is_exact_no_provider_no_event_fallback(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("You mentioned Redis in your architecture", False, False)
    )
    calls = 0

    def forbidden_factory(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("prediction provider must not be constructed")

    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: _settings(prediction_enabled=False),
    )
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        registry,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: stt,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_prediction_provider",
        forbidden_factory,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"partial")
        transcript = websocket.receive_json()
        assert transcript["type"] == "transcript.partial"
        websocket.send_json({"type": "stop"})
        _, seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "status"
            and event.get("status") == "stopped",
        )
        assert all(event["type"] != "prediction.snapshot" for event in seen)

    assert calls == 0


def test_prediction_failure_cannot_interrupt_canonical_turn_or_answer(monkeypatch) -> None:
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("Explain Redis failover", False, False),
        TranscriptResult("Explain Redis failover", True, True),
        TranscriptResult("The transcript remains healthy.", True, True),
    )
    predictor = FakePredictionProvider(
        [
            FakePredictionScript(
                error=PredictionProviderError(
                    PredictionFailureCategory.RATE_LIMIT,
                    "Prediction is temporarily rate limited.",
                    retryable=True,
                )
            )
        ]
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Use replication."),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: _settings(answer_enabled=True),
    )
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: stt,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_prediction_provider",
        lambda _settings: predictor,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_answer_provider",
        lambda _settings: answer,
    )

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"partial-question")
        failed, partial_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "prediction.snapshot"
            and event.get("state") == "failed",
        )
        assert failed["error_category"] == "rate_limit"
        assert any(event["type"] == "transcript.partial" for event in partial_seen)

        websocket.send_bytes(b"final-question")
        completed, authoritative_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "answer.completed",
            limit=24,
        )
        authoritative_types = [event["type"] for event in authoritative_seen]
        assert "transcript.final" in authoritative_types
        assert "turn.finalized" in authoritative_types
        assert "question.detected" in authoritative_types
        assert "answer.started" in authoritative_types
        assert any(
            event.get("type") == "answer.delta"
            and event.get("text") == "Use replication."
            for event in authoritative_seen
        )

        websocket.send_bytes(b"healthy-statement")
        turn, healthy_seen = _receive_until(
            websocket,
            lambda event: event.get("type") == "turn.finalized",
            limit=12,
        )
        assert turn["text"] == "The transcript remains healthy."
        assert any(event["type"] == "transcript.final" for event in healthy_seen)

        websocket.send_json({"type": "stop"})
        _receive_until(
            websocket,
            lambda event: event.get("type") == "status"
            and event.get("status") == "stopped",
        )

    assert len(predictor.requests) == 1
    assert len(answer.requests) == 1
    assert stt.closed is True
    assert registry.size == 0


def test_disconnect_resume_replays_no_prediction_and_makes_no_paid_call(
    monkeypatch,
) -> None:
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_stt = ControlledSTTProvider(
        TranscriptResult("You mentioned Redis in your architecture", False, False)
    )
    resumed_stt = ControlledSTTProvider(
        TranscriptResult("You mentioned Redis in your architecture", True, True),
        TranscriptResult("Can you explain Redis failover", False, False),
    )
    providers = iter((first_stt, resumed_stt))
    predictor = FakePredictionProvider(
        [
            FakePredictionScript(result=_result("Why Redis?", "redis")),
            FakePredictionScript(
                result=_result("How does Redis failover work?", "failover")
            ),
        ]
    )
    monkeypatch.setattr("app.api.websocket.get_settings", lambda: _settings())
    monkeypatch.setattr("app.api.websocket.transcription_session_registry", registry)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: next(providers),
    )
    monkeypatch.setattr(
        "app.api.websocket.create_prediction_provider",
        lambda _settings: predictor,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcribe") as websocket:
            session = _start(websocket)
            websocket.send_bytes(b"first-prefix")
            _receive_until(
                websocket,
                lambda event: event.get("type") == "prediction.snapshot"
                and event.get("state") == "ready",
            )
            assert len(predictor.requests) == 1

        with client.websocket_connect("/ws/transcribe") as websocket:
            assert websocket.receive_json()["status"] == "connecting"
            websocket.send_json(
                {"type": "session.resume", "resume_token": session["resume_token"]}
            )
            _, replay_seen = _receive_until(
                websocket,
                lambda event: event.get("type") == "status"
                and event.get("status") == "ready",
                limit=16,
            )
            assert all(
                event.get("type") != "prediction.snapshot" for event in replay_seen
            )
            assert len(predictor.requests) == 1

            websocket.send_bytes(b"close-gap")
            _receive_until(
                websocket,
                lambda event: event.get("type") == "turn.finalized",
                limit=12,
            )
            assert len(predictor.requests) == 1

            websocket.send_bytes(b"new-prefix")
            ready, _ = _receive_until(
                websocket,
                lambda event: event.get("type") == "prediction.snapshot"
                and event.get("state") == "ready",
                limit=12,
            )
            assert ready["candidates"][0]["text"] == (
                "How does Redis failover work?"
            )
            assert len(predictor.requests) == 2

            websocket.send_json({"type": "stop"})
            _receive_until(
                websocket,
                lambda event: event.get("type") == "status"
                and event.get("status") == "stopped",
            )

    assert first_stt.closed is True
    assert resumed_stt.closed is True
    assert registry.size == 0
