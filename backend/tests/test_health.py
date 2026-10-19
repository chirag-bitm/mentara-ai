from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "Mentara AI API"
    assert response.json()["stt_provider"] == "gemini"
    assert response.json()["stt_model"] == "gemini-3.5-transcribe-live"


def test_websocket_health() -> None:
    with client.websocket_connect("/ws/health") as websocket:
        websocket.send_text("ping")
        event = websocket.receive_json()
        assert event == {
            "type": "pong",
            "message": "WebSocket connection is working.",
        }


def test_transcription_socket_reports_missing_gemini_key(monkeypatch) -> None:
    unconfigured_settings = Settings(_env_file=None, gemini_api_key=None)
    monkeypatch.setattr(
        "app.api.websocket.get_settings",
        lambda: unconfigured_settings,
    )

    with client.websocket_connect("/ws/transcribe") as websocket:
        event = websocket.receive_json()

    assert event == {
        "type": "error",
        "code": "STT_NOT_CONFIGURED",
        "message": "GEMINI_API_KEY is missing in backend/.env.",
    }
