import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.api.websocket import handle_provider_lifecycle
from app.main import app
from app.services.stt.base import TranscriptResult
from app.services.stt.rotation import (
    ProviderLifecycleEvent,
    ProviderLifecycleEventKind,
)
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)


class FakeSTTProvider:
    def __init__(self) -> None:
        self.closed = False

    async def connect(self) -> None:
        return None

    async def send_audio(self, audio: bytes) -> None:
        return None

    async def finish(self) -> None:
        return None

    async def results(self) -> AsyncIterator[TranscriptResult]:
        results = (
            TranscriptResult("Can you", False, False),
            TranscriptResult("Can you explain", False, False),
            TranscriptResult("Can you explain", False, False),
            TranscriptResult("Can you explain Redis?", True, True),
            TranscriptResult("Can you explain Redis?", True, True),
        )
        for result in results:
            yield result

    async def close(self) -> None:
        self.closed = True


class FakeStatusWebSocket:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def send_json(self, event: dict[str, object]) -> None:
        self.events.append(event)


def test_transcribe_routes_provider_results_through_canonical_aggregator(
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        conversation_analysis_enabled=False,
        answer_generation_enabled=False,
    )
    provider = FakeSTTProvider()
    monkeypatch.setattr("app.api.websocket.get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.api.websocket.create_resilient_stt_provider",
        lambda _settings, lifecycle_callback=None: provider,
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/transcribe") as websocket:
        assert websocket.receive_json() == {
            "type": "status",
            "status": "connecting",
            "message": "Connecting to streaming STT…",
        }
        websocket.send_json({"type": "session.start"})
        events = [websocket.receive_json() for _ in range(6)]

    assert events[0]["type"] == "session.ready"
    assert events[0]["resumed"] is False
    assert events[0]["resume_ttl_seconds"] == 30.0
    assert events[1] == {
        "type": "status",
        "status": "ready",
        "message": "Streaming STT is ready.",
    }
    assert events[-1] == {
        "type": "status",
        "status": "stopped",
        "message": "Transcription stopped.",
    }

    transcript_events = events[2:5]
    assert [event["type"] for event in transcript_events] == [
        "transcript.partial",
        "transcript.partial",
        "transcript.final",
    ]
    assert [event["sequence"] for event in transcript_events] == [1, 2, 3]
    assert [event["revision"] for event in transcript_events] == [1, 2, 3]
    assert len({event["session_id"] for event in transcript_events}) == 1
    assert len({event["utterance_id"] for event in transcript_events}) == 1
    assert [event["text"] for event in transcript_events] == [
        "Can you",
        "Can you explain",
        "Can you explain Redis?",
    ]
    assert [event["is_final"] for event in transcript_events] == [
        False,
        False,
        True,
    ]
    assert all(event["audio_source"] == "microphone" for event in transcript_events)
    assert all(event["speaker_role"] == "local_user" for event in transcript_events)
    assert all(event["first_seen_ms"] >= 0 for event in transcript_events)
    assert all(event["last_updated_ms"] >= 0 for event in transcript_events)
    assert "finalized_ms" not in transcript_events[0]
    assert "finalized_ms" in transcript_events[-1]
    assert all("confidence" not in event for event in transcript_events)
    assert provider.closed is True


def test_rotation_lifecycle_updates_session_generation_and_browser_status() -> None:
    async def scenario() -> None:
        events: list[dict[str, object]] = []
        session = TranscriptionSession()
        session.transition(SessionConnectionState.CONNECTED)

        for kind, reason, message in (
            (
                ProviderLifecycleEventKind.DEGRADED,
                "forced_rotation",
                "Recent words may be incomplete.",
            ),
            (
                ProviderLifecycleEventKind.RECONNECTING,
                "planned_rotation",
                "Refreshing the streaming STT connection…",
            ),
            (
                ProviderLifecycleEventKind.RECONNECTED,
                "replacement_connected",
                "Streaming STT reconnected.",
            ),
        ):
            await handle_provider_lifecycle(
                session,
                ProviderLifecycleEvent(
                    kind=kind,
                    generation=1,
                    reason=reason,
                    message=message,
                ),
                lambda event: events.append(
                    event.model_dump(mode="json", exclude_none=True)
                ),
            )

        assert session.connection_state is SessionConnectionState.CONNECTED
        assert session.provider_generation == 2
        assert [event["status"] for event in events] == [
            "degraded",
            "reconnecting",
            "ready",
        ]

    asyncio.run(scenario())
