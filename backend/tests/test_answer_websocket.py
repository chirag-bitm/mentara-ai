import asyncio
import json
import logging
from collections import deque
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import app
from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
)
from app.services.answer.provider import AnswerProviderError
from app.services.stt.base import TranscriptResult
from app.services.transcript.registry import InMemoryTranscriptionSessionRegistry


class ControlledSTTProvider:
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


def _settings(
    *,
    enabled: bool = True,
    memory_enabled: bool = True,
) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        conversation_analysis_enabled=True,
        conversation_turn_merge_window_ms=0,
        answer_generation_enabled=enabled,
        memory_context_enabled=memory_enabled,
        prediction_enabled=False,
        answer_generation_timeout_seconds=2,
    )


def _configure(
    monkeypatch,
    registry,
    stt_providers,
    answer_provider,
    *,
    enabled=True,
    memory_enabled=True,
):
    providers = iter(stt_providers)
    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: _settings(enabled=enabled, memory_enabled=memory_enabled),
    )
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        registry,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: next(providers),
    )
    monkeypatch.setattr(
        "app.api.websocket.create_answer_provider",
        lambda _settings: answer_provider,
    )


def _start(websocket):
    assert websocket.receive_json()["status"] == "connecting"
    websocket.send_json({"type": "session.start"})
    session = websocket.receive_json()
    assert session["type"] == "session.ready"
    assert websocket.receive_json()["status"] == "ready"
    return session


def _receive_question(websocket):
    transcript = websocket.receive_json()
    turn = websocket.receive_json()
    detection = websocket.receive_json()
    assert [transcript["type"], turn["type"], detection["type"]] == [
        "transcript.final",
        "turn.finalized",
        "question.detected",
    ]
    return transcript, turn, detection


def _receive_statement(websocket):
    transcript = websocket.receive_json()
    turn = websocket.receive_json()
    assert [transcript["type"], turn["type"]] == [
        "transcript.final",
        "turn.finalized",
    ]
    return transcript, turn


def _stop(websocket):
    websocket.send_json({"type": "stop"})
    assert websocket.receive_json()["status"] == "stopping"
    assert websocket.receive_json()["status"] == "stopped"


def test_positive_detection_streams_one_answer_with_stable_provenance(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult(
            "Give eight short differences between a process and a thread.",
            True,
            True,
        )
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Processes are "),
                    AnswerProviderTextDelta(sequence=2, text="isolated; threads share memory."),
                    AnswerProviderCompleted(sequence=3),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _, turn, detection = _receive_question(websocket)
        started = websocket.receive_json()
        delta = websocket.receive_json()
        completed = websocket.receive_json()

        assert started["type"] == "answer.started"
        assert delta["type"] == "answer.delta"
        assert delta["text"] == "Processes are isolated; threads share memory."
        assert delta["from_stream_sequence"] == 1
        assert delta["stream_sequence"] == 2
        assert completed["type"] == "answer.completed"
        assert completed["answer_id"] == started["answer_id"] == delta["answer_id"]
        assert completed["detection_id"] == detection["detection_id"]
        assert completed["source_turn_id"] == turn["turn_id"]
        _stop(websocket)

    assert len(answer.requests) == 1
    assert registry.size == 0


def test_memory_context_reaches_provider_with_recent_and_relevant_older_turns(
    monkeypatch,
):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("We use Redis as our caching layer.", True, True),
        TranscriptResult("The deployment completed successfully.", True, True),
        TranscriptResult("The weather is improving today.", True, True),
        TranscriptResult("The team met in the afternoon.", True, True),
        TranscriptResult("The documentation was updated yesterday.", True, True),
        TranscriptResult(
            "Coming back to Redis, why not use DynamoDB?",
            True,
            True,
        ),
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Redis answer"),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        for index in range(5):
            websocket.send_bytes(f"statement-{index}".encode())
            _receive_statement(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        assert websocket.receive_json()["type"] == "answer.delta"
        assert websocket.receive_json()["type"] == "answer.completed"

        payload = json.loads(answer.requests[0].prompt.user_content)
        assert payload["memory_context"]["revision"] == 6
        assert payload["memory_context"]["continuity"] == "normal"
        assert [
            turn["text"] for turn in payload["recent_finalized_turns"]
        ] == [
            "The deployment completed successfully.",
            "The weather is improving today.",
            "The team met in the afternoon.",
            "The documentation was updated yesterday.",
        ]
        assert [turn["text"] for turn in payload["relevant_older_turns"]] == [
            "We use Redis as our caching layer."
        ]
        assert all(
            turn["source_kind"] == "verbatim_conversation"
            and turn["trust"] == "untrusted"
            for turn in (
                *payload["recent_finalized_turns"],
                *payload["relevant_older_turns"],
                payload["current_request"],
            )
        )
        _stop(websocket)


def test_memory_feature_disabled_restores_m4_prompt_shape(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("We use Redis as our caching layer.", True, True),
        TranscriptResult("Why?", True, True),
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Because..."),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    _configure(
        monkeypatch,
        registry,
        [stt],
        answer,
        memory_enabled=False,
    )

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"statement")
        _receive_statement(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        assert websocket.receive_json()["type"] == "answer.delta"
        assert websocket.receive_json()["type"] == "answer.completed"
        payload = json.loads(answer.requests[0].prompt.user_content)
        assert set(payload) == {
            "context_notice",
            "assistance_kind",
            "recent_finalized_turns",
            "current_request",
        }
        assert payload["recent_finalized_turns"][0]["text"] == (
            "We use Redis as our caching layer."
        )
        assert "source_kind" not in payload["recent_finalized_turns"][0]
        _stop(websocket)


def test_generated_answer_is_not_inserted_into_conversation_memory(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    stt = ControlledSTTProvider(TranscriptResult("Explain Redis.", True, True))
    generated_text = "A provider-generated answer that must remain separate."
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text=generated_text),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcribe") as websocket:
            session = _start(websocket)
            websocket.send_bytes(b"question")
            _receive_question(websocket)
            assert websocket.receive_json()["type"] == "answer.started"
            assert websocket.receive_json()["type"] == "answer.delta"
            assert websocket.receive_json()["type"] == "answer.completed"

        lease = registry.attach(session["resume_token"])
        memory = lease.session.memory_snapshot()
        answers = lease.session.answer_runtime.snapshot()
        assert memory is not None
        assert memory.stored_turn_count == 1
        assert [entry.text for entry in memory.entries] == ["Explain Redis."]
        assert generated_text not in {entry.text for entry in memory.entries}
        assert len(answers.answers) == 1
        registry.remove(lease)


def test_normal_logs_do_not_include_transcript_memory_or_answer_bodies(
    monkeypatch,
    caplog,
):
    transcript_sentinel = "LOG_PRIVATE_TRANSCRIPT_SENTINEL"
    answer_sentinel = "LOG_PRIVATE_ANSWER_SENTINEL"
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult(f"Explain Redis and {transcript_sentinel}?", True, True)
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text=answer_sentinel),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)
    caplog.set_level(logging.INFO)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        assert websocket.receive_json()["type"] == "answer.delta"
        assert websocket.receive_json()["type"] == "answer.completed"
        _stop(websocket)

    rendered_logs = "\n".join(record.getMessage() for record in caplog.records)
    assert transcript_sentinel not in rendered_logs
    assert answer_sentinel not in rendered_logs


def test_stt_remains_responsive_while_answer_stream_is_blocked(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("Explain Redis.", True, True),
        TranscriptResult("The deployment completed.", True, True),
    )
    finish_gate = asyncio.Event()
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Partial answer"),
                    AnswerProviderCompleted(sequence=2),
                ),
                step_gates=(None, finish_gate),
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        assert websocket.receive_json()["type"] == "answer.delta"

        websocket.send_bytes(b"statement while answering")
        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.finalized"

        finish_gate.set()
        assert websocket.receive_json()["type"] == "answer.completed"
        _stop(websocket)

    assert len(answer.requests) == 1


def test_stop_while_streaming_cancels_answer_provider(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(TranscriptResult("Explain Redis.", True, True))
    blocked = asyncio.Event()
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Partial"),
                    AnswerProviderCompleted(sequence=2),
                ),
                step_gates=(None, blocked),
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        assert websocket.receive_json()["type"] == "answer.delta"
        websocket.send_json({"type": "stop"})
        assert websocket.receive_json()["status"] == "stopping"
        cancelled = websocket.receive_json()
        assert cancelled["type"] == "answer.cancelled"
        assert websocket.receive_json()["status"] == "stopped"

    assert answer.streams[0].cancelled
    assert answer.streams[0].closed
    assert registry.size == 0


def test_disconnect_resume_replays_active_answer_without_new_provider_call(
    monkeypatch,
):
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_stt = ControlledSTTProvider(TranscriptResult("Explain Redis.", True, True))
    resumed_stt = ControlledSTTProvider()
    finish_gate = asyncio.Event()
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Partial"),
                    AnswerProviderCompleted(sequence=2),
                ),
                step_gates=(None, finish_gate),
            )
        ]
    )
    _configure(monkeypatch, registry, [first_stt, resumed_stt], answer)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcribe") as websocket:
            session = _start(websocket)
            websocket.send_bytes(b"question")
            original = list(_receive_question(websocket))
            assert websocket.receive_json()["type"] == "answer.started"
            assert websocket.receive_json()["type"] == "answer.delta"

        with client.websocket_connect("/ws/transcribe") as websocket:
            assert websocket.receive_json()["status"] == "connecting"
            websocket.send_json(
                {"type": "session.resume", "resume_token": session["resume_token"]}
            )
            assert websocket.receive_json()["status"] == "reconnecting"
            assert websocket.receive_json()["resumed"] is True
            assert websocket.receive_json()["status"] == "degraded"
            assert [websocket.receive_json() for _ in range(3)] == original
            replayed = websocket.receive_json()
            assert replayed["type"] == "answer.snapshot"
            assert replayed["state"] == "streaming"
            assert replayed["text"] == "Partial"
            assert websocket.receive_json()["status"] == "ready"
            assert len(answer.requests) == 1

            finish_gate.set()
            assert websocket.receive_json()["type"] == "answer.completed"
            _stop(websocket)

    assert len(answer.requests) == 1


def test_disconnect_resume_replays_completed_answer_without_new_provider_call(
    monkeypatch,
):
    registry = InMemoryTranscriptionSessionRegistry(resume_ttl_seconds=30)
    first_stt = ControlledSTTProvider(TranscriptResult("Explain Redis.", True, True))
    resumed_stt = ControlledSTTProvider()
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderTextDelta(sequence=1, text="Completed answer"),
                    AnswerProviderCompleted(sequence=2),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [first_stt, resumed_stt], answer)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/transcribe") as websocket:
            session = _start(websocket)
            websocket.send_bytes(b"question")
            original = list(_receive_question(websocket))
            assert websocket.receive_json()["type"] == "answer.started"
            assert websocket.receive_json()["type"] == "answer.delta"
            assert websocket.receive_json()["type"] == "answer.completed"

        with client.websocket_connect("/ws/transcribe") as websocket:
            assert websocket.receive_json()["status"] == "connecting"
            websocket.send_json(
                {"type": "session.resume", "resume_token": session["resume_token"]}
            )
            assert websocket.receive_json()["status"] == "reconnecting"
            assert websocket.receive_json()["resumed"] is True
            assert websocket.receive_json()["status"] == "degraded"
            assert [websocket.receive_json() for _ in range(3)] == original
            replayed = websocket.receive_json()
            assert replayed["type"] == "answer.snapshot"
            assert replayed["state"] == "completed"
            assert replayed["text"] == "Completed answer"
            assert websocket.receive_json()["status"] == "ready"
            assert len(answer.requests) == 1
            _stop(websocket)

    assert len(answer.requests) == 1


def test_answer_failure_does_not_stop_healthy_stt(monkeypatch):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("Explain Redis.", True, True),
        TranscriptResult("The session is still healthy.", True, True),
    )
    answer = FakeAnswerProvider(
        [
            FakeAnswerScript(
                steps=(
                    AnswerProviderError(
                        AnswerFailureCategory.RATE_LIMIT,
                        "Answer provider is temporarily rate limited.",
                        retryable=True,
                    ),
                )
            )
        ]
    )
    _configure(monkeypatch, registry, [stt], answer)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        assert websocket.receive_json()["type"] == "answer.started"
        failed = websocket.receive_json()
        assert failed["type"] == "answer.failed"
        assert failed["error_category"] == "rate_limit"

        websocket.send_bytes(b"statement")
        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.finalized"
        _stop(websocket)

    assert stt.closed


def test_feature_disabled_keeps_question_detection_without_provider_call(
    monkeypatch,
):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(TranscriptResult("What is Redis?", True, True))
    answer_factory_called = False

    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: _settings(enabled=False),
    )
    monkeypatch.setattr(
        "app.api.websocket.transcription_session_registry",
        registry,
    )
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda *_args, **_kwargs: stt,
    )

    def answer_factory(_settings):
        nonlocal answer_factory_called
        answer_factory_called = True
        raise AssertionError("disabled M4 must not construct an answer provider")

    monkeypatch.setattr("app.api.websocket.create_answer_provider", answer_factory)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        _stop(websocket)

    assert answer_factory_called is False


def test_answer_configuration_failure_preserves_transcription_and_detection(
    monkeypatch,
):
    registry = InMemoryTranscriptionSessionRegistry()
    stt = ControlledSTTProvider(
        TranscriptResult("What is Redis?", True, True),
        TranscriptResult("The transcript remains healthy.", True, True),
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

    def unavailable(_settings):
        raise AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            "Answer generation is not configured.",
            retryable=False,
        )

    monkeypatch.setattr("app.api.websocket.create_answer_provider", unavailable)

    with TestClient(app).websocket_connect("/ws/transcribe") as websocket:
        _start(websocket)
        websocket.send_bytes(b"question")
        _receive_question(websocket)
        websocket.send_bytes(b"statement")
        assert websocket.receive_json()["type"] == "transcript.final"
        assert websocket.receive_json()["type"] == "turn.finalized"
        _stop(websocket)

    assert stt.closed
    assert registry.size == 0
