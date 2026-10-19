"""Guard the paid benchmark's stop-on-failure and token-cost accounting."""

import asyncio
import json
import sys
from pathlib import Path

from pydantic import SecretStr

from app.core.config import Settings
from app.services.prediction import (
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionProviderError,
    PredictionProviderResult,
    PredictionUsage,
)


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import benchmark_predictions as benchmark  # noqa: E402


def _test_settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key=SecretStr("test-only-key"))


def test_benchmark_stops_after_first_provider_failure(monkeypatch, tmp_path) -> None:
    class FailingProvider:
        def __init__(self, **kwargs) -> None:
            self.calls = 0

        async def predict(self, request):
            self.calls += 1
            raise PredictionProviderError(
                PredictionFailureCategory.PROVIDER_SERVER,
                "Gemini did not complete prediction.",
                retryable=False,
                provider_reason="interaction_incomplete",
            )

    provider = FailingProvider()
    monkeypatch.setattr(benchmark, "Settings", lambda **kwargs: _test_settings())
    monkeypatch.setattr(benchmark, "GeminiPredictionProvider", lambda **kwargs: provider)
    output = tmp_path / "benchmark.json"
    monkeypatch.setattr(benchmark, "RESULT_PATH", output)

    assert asyncio.run(benchmark.main()) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert provider.calls == report["request_count"] == 1
    assert report["planned_request_count"] == 4
    assert report["successful_request_count"] == 0
    assert len(report["aborted_case_ids"]) == 4
    assert report["estimated_total_cost_usd"] is None
    assert report["runs"][0]["error"]["provider_reason"] == "interaction_incomplete"


def test_benchmark_counts_thought_tokens_and_requires_all_calls(
    monkeypatch, tmp_path
) -> None:
    class WorkingProvider:
        def __init__(self, **kwargs) -> None:
            self.calls = 0

        async def predict(self, request):
            self.calls += 1
            assert request.max_output_tokens == 512
            return PredictionProviderResult(
                candidates=(
                    PredictionCandidate(
                        kind=PredictionCandidateKind.QUESTION,
                        text="What will happen next?",
                        anchor_terms=("next",),
                    ),
                ),
                usage=PredictionUsage(
                    input_tokens=100, output_tokens=20, total_tokens=170
                ),
            )

    provider = WorkingProvider()
    monkeypatch.setattr(benchmark, "Settings", lambda **kwargs: _test_settings())
    monkeypatch.setattr(benchmark, "GeminiPredictionProvider", lambda **kwargs: provider)
    output = tmp_path / "benchmark.json"
    monkeypatch.setattr(benchmark, "RESULT_PATH", output)

    assert asyncio.run(benchmark.main()) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert provider.calls == report["request_count"] == 4
    assert report["suppressed_case_count"] == 1
    assert report["aborted_case_ids"] == []
    assert report["estimated_total_cost_usd"] == 0.00082
    assert all(
        run["billed_output_token_proxy"] == 70
        for run in report["runs"]
        if run["provider_called"]
    )
