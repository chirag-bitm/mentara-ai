"""One-call alternative-model benchmark stays isolated from production."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr

from app.core.config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import probe_prediction_fast_model as probe  # noqa: E402


class FakeClient:
    def __init__(self, *, output: str, status: str = "completed") -> None:
        self.output = output
        self.status = status
        self.requests = []
        self.closed = False
        self.aio = self
        self.interactions = self

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            status=self.status,
            output_text=self.output,
            usage=SimpleNamespace(
                total_input_tokens=100,
                total_output_tokens=20,
                total_tokens=120,
            ),
        )

    async def aclose(self):
        self.closed = True


def test_alternative_model_imports_isolated_without_provider_calls(tmp_path) -> None:
    script = Path(probe.__file__).resolve()
    process = subprocess.run(
        [sys.executable, "-I", "-c", "import runpy; runpy.run_path(" + repr(str(script)) + ")"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == ""


def test_alternative_model_one_stateless_bounded_call_no_thinking_level() -> None:
    output = json.dumps({
        "candidates": [{
            "kind": "question",
            "text": "Why did you choose Redis?",
            "anchor_terms": ["Redis", "choose"],
        }]
    })
    fake = FakeClient(output=output)
    result = asyncio.run(probe.probe_one_request(
        api_key="local-test-key", client_factory=lambda **kwargs: fake
    ))
    assert result["candidate_count"] == 1
    assert result["fixed_case_redis_anchor_present"] is True
    assert result["complete_valid_ms"] >= 0
    assert result["usage"]["total_tokens"] == 120
    assert "Redis" not in json.dumps(result)
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request["model"] == "gemini-2.5-flash-lite"
    assert request["stream"] is False and request["store"] is False
    assert "tools" not in request
    assert "previous_interaction_id" not in request
    assert request["generation_config"] == {"max_output_tokens": 256}
    assert request["response_format"]["schema"]["properties"]["candidates"]["maxItems"] == 1
    assert fake.closed


def test_malformed_output_closes_client_and_does_not_enter_app_state() -> None:
    fake = FakeClient(output='{"candidates": [', status="completed")
    try:
        asyncio.run(probe.probe_one_request(
            api_key="local-test-key", client_factory=lambda **kwargs: fake
        ))
    except ValueError:
        pass
    else:
        raise AssertionError("Malformed provider output was accepted")
    assert fake.closed
    assert len(fake.requests) == 1


def test_failure_report_does_not_save_exception_or_key(monkeypatch, tmp_path) -> None:
    class FailingClient:
        def __init__(self, **kwargs):
            raise ValueError("DO_NOT_SAVE_PRIVATE_SPEECH_OR_KEY")

    monkeypatch.setattr(probe, "Settings", lambda **kwargs: Settings(
        _env_file=None, gemini_api_key=SecretStr("local-test-key")
    ))
    monkeypatch.setattr(probe.genai, "Client", FailingClient)

    async def fail(*, api_key):
        await probe.probe_one_request(api_key=api_key, client_factory=FailingClient)

    monkeypatch.setattr(probe, "probe_one_request", fail)
    output = tmp_path / "probe.json"
    monkeypatch.setattr(probe, "RESULT_PATH", output)
    assert asyncio.run(probe.main()) == 1
    text = output.read_text(encoding="utf-8")
    assert "DO_NOT_SAVE_PRIVATE_SPEECH_OR_KEY" not in text
    assert "local-test-key" not in text
    report = json.loads(text)
    assert report["max_calls"] == 1
    assert report["run"]["error"] == "probe_failed"
