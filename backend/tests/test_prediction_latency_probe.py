"""Keep the optional two-call probe bounded and independent of the runtime."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.core.config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import probe_prediction_latency as probe  # noqa: E402


def _test_settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key=SecretStr("local-test-key"))


def test_probe_imports_from_a_foreign_working_directory_without_api_calls(
    tmp_path,
) -> None:
    # Running a file by path puts scripts/, not its parent, on sys.path.
    # -I also removes accidental PYTHONPATH/pytest paths from this check.
    script = Path(probe.__file__).resolve()
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import runpy; runpy.run_path(" + repr(str(script)) + ")",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == ""


def _event(event_type: str, *, text: str | None = None):
    if text is not None:
        return SimpleNamespace(
            event_type=event_type,
            delta=SimpleNamespace(type="text", text=text),
        )
    return SimpleNamespace(
        event_type=event_type,
        interaction=SimpleNamespace(
            usage=SimpleNamespace(
                total_input_tokens=123,
                total_output_tokens=30,
                total_tokens=153,
            )
        ),
    )


class FakeStreamClient:
    def __init__(self, fragments: tuple[str, ...], *, completed: bool = True):
        self.fragments = fragments
        self.completed = completed
        self.requests = []
        self.closed = False
        self.aio = self
        self.interactions = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)

        async def events():
            for fragment in self.fragments:
                yield _event("step.delta", text=fragment)
            if self.completed:
                yield _event("interaction.completed")

        return events()

    async def aclose(self):
        self.closed = True


def test_stream_probe_requires_complete_valid_result_and_stateless_request() -> None:
    payload = json.dumps({
        "candidates": [{
            "kind": "question",
            "text": "How does Redis recover?",
            "anchor_terms": ["Redis"],
        }]
    })
    client = FakeStreamClient((payload[:12], payload[12:]))
    request = probe._request()
    assert request.max_candidates == 1
    assert request.max_output_tokens == 256

    report = asyncio.run(probe.probe_stream(
        request,
        api_key="local-test-key",
        model="gemini-3.5-flash-lite",
        thinking_level="minimal",
        client_factory=lambda **kwargs: client,
    ))

    assert report["candidate_count"] == 1
    assert report["first_text_ms"] is not None
    assert report["first_valid_json_ms"] is not None
    assert report["complete_valid_ms"] >= report["first_valid_json_ms"]
    assert report["usage"]["input_tokens"] == 123
    assert "Redis" not in json.dumps(report)
    assert len(client.requests) == 1
    sent = client.requests[0]
    assert sent["stream"] is True
    assert sent["store"] is False
    assert "tools" not in sent
    assert "previous_interaction_id" not in sent
    assert sent["generation_config"]["max_output_tokens"] == 256
    assert sent["response_format"]["schema"]["properties"]["candidates"]["maxItems"] == 1
    assert client.closed


@pytest.mark.parametrize(
    ("fragments", "completed"),
    [(("{broken",), True), (("{" + '"candidates":[]}',), False)],
)
def test_stream_probe_rejects_malformed_or_incomplete_stream(
    fragments, completed
) -> None:
    client = FakeStreamClient(fragments, completed=completed)
    with pytest.raises(ValueError):
        asyncio.run(probe.probe_stream(
            probe._request(),
            api_key="local-test-key",
            model="gemini-3.5-flash-lite",
            thinking_level="minimal",
            client_factory=lambda **kwargs: client,
        ))
    assert client.closed


def test_probe_stops_at_first_error_and_writes_no_sensitive_text(
    monkeypatch, tmp_path
) -> None:
    calls = []

    async def failing_first(request, **kwargs):
        calls.append(request)
        raise ValueError("DO_NOT_WRITE_PRIVATE_CONVERSATION")

    async def forbidden_second(request, **kwargs):
        raise AssertionError("A failed first call must abort the second")

    monkeypatch.setattr(probe, "Settings", lambda **kwargs: _test_settings())
    monkeypatch.setattr(probe, "probe_nonstream", failing_first)
    monkeypatch.setattr(probe, "probe_stream", forbidden_second)
    output = tmp_path / "probe.json"
    monkeypatch.setattr(probe, "RESULT_PATH", output)

    assert asyncio.run(probe.main()) == 1
    raw = output.read_text(encoding="utf-8")
    assert "DO_NOT_WRITE_PRIVATE_CONVERSATION" not in raw
    assert "local-test-key" not in raw
    result = json.loads(raw)
    assert len(calls) == result["actual_calls"] == 1
    assert result["max_calls"] == 2
    assert result["runs"][0]["error"] == "probe_failed"
