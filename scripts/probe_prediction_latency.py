"""Two-call, non-sensitive latency experiment; never used by the live runtime.

Run only on a configured checkpoint. Output includes timings and usage, never
conversation text, candidates, credentials, or raw provider exceptions.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable

from google import genai

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings  # noqa: E402
from app.services.prediction.gemini import (  # noqa: E402
    GeminiPredictionProvider,
    _GeminiPredictionOutput,
)
from app.services.prediction.provider import PredictionProviderRequest  # noqa: E402
from scripts.benchmark_predictions import (  # noqa: E402
    CASE_IDS,
    CORPUS_PATH,
    _provider_request,
)


RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_5_5_LATENCY_PROBE.json"
CASE_ID = "technical_follow_up"
MAX_OUTPUT_TOKENS = 256
MAX_STREAM_CHARS = 4_096
TIMEOUT_SECONDS = 12


def _elapsed_ms(started_ns: int) -> int:
    return round((perf_counter_ns() - started_ns) / 1_000_000)


def _usage(event: Any) -> dict[str, int | None]:
    usage = getattr(getattr(event, "interaction", event), "usage", None)
    return {
        "input_tokens": _nonnegative_int(getattr(usage, "total_input_tokens", None)),
        "output_tokens": _nonnegative_int(getattr(usage, "total_output_tokens", None)),
        "total_tokens": _nonnegative_int(getattr(usage, "total_tokens", None)),
    }


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _request() -> PredictionProviderRequest:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    case = next(case for case in corpus["cases"] if case["case_id"] == CASE_ID)
    assert CASE_ID in CASE_IDS
    trigger, request = _provider_request(case, 1, MAX_OUTPUT_TOKENS)
    if request is None or not trigger.eligible:
        raise ValueError("The fixed latency probe case is ineligible")
    return replace(request, max_candidates=1)


async def probe_nonstream(
    request: PredictionProviderRequest,
    *,
    api_key: str,
    model: str,
    thinking_level: str,
    client_factory: Callable[..., Any] = genai.Client,
) -> dict[str, Any]:
    provider = GeminiPredictionProvider(
        api_key=api_key,
        model=model,
        thinking_level=thinking_level,
        client_factory=client_factory,
    )
    started_ns = perf_counter_ns()
    async with asyncio.timeout(TIMEOUT_SECONDS):
        result = await provider.predict(request)
    if len(result.candidates) != 1:
        raise ValueError("The nonstream probe returned no valid candidate")
    usage = result.usage
    return {
        "method": "one_candidate_nonstream",
        "complete_valid_ms": _elapsed_ms(started_ns),
        "first_text_ms": None,
        "first_valid_json_ms": None,
        "candidate_count": len(result.candidates),
        "usage": {
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
        },
    }


async def probe_stream(
    request: PredictionProviderRequest,
    *,
    api_key: str,
    model: str,
    thinking_level: str,
    client_factory: Callable[..., Any] = genai.Client,
) -> dict[str, Any]:
    schema = _GeminiPredictionOutput.model_json_schema()
    schema["properties"]["candidates"]["maxItems"] = 1
    client = client_factory(
        api_key=api_key,
        http_options={"retry_options": {"attempts": 0}},
    ).aio
    parts: list[str] = []
    total_chars = 0
    first_text_ms: int | None = None
    first_valid_json_ms: int | None = None
    started_ns = perf_counter_ns()
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            stream = await client.interactions.create(
                model=model,
                input=[{
                    "type": "user_input",
                    "content": [{"type": "text", "text": request.prompt.user_content}],
                }],
                system_instruction=request.prompt.system_instruction,
                generation_config={
                    "thinking_level": thinking_level,
                    "max_output_tokens": request.max_output_tokens,
                },
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
                stream=True,
                store=False,
            )
            completed = None
            async for event in stream:
                event_type = getattr(event, "event_type", None)
                if event_type == "step.delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) != "text":
                        continue
                    value = getattr(delta, "text", None)
                    if not isinstance(value, str):
                        raise ValueError("Invalid streamed text delta")
                    if first_text_ms is None and value:
                        first_text_ms = _elapsed_ms(started_ns)
                    total_chars += len(value)
                    if total_chars > MAX_STREAM_CHARS:
                        raise ValueError("Stream exceeded the bounded buffer")
                    parts.append(value)
                    if first_valid_json_ms is None:
                        try:
                            parsed = _GeminiPredictionOutput.model_validate_json(
                                "".join(parts)
                            )
                            if len(parsed.candidates) == 1:
                                first_valid_json_ms = _elapsed_ms(started_ns)
                        except ValueError:
                            pass
                elif event_type == "interaction.completed":
                    completed = event
                    break
                elif event_type == "error":
                    raise ValueError("Stream ended with a provider error")
            if completed is None:
                raise ValueError("Stream did not complete")
            parsed = _GeminiPredictionOutput.model_validate_json("".join(parts))
            if len(parsed.candidates) != 1:
                raise ValueError("Stream returned no valid candidate")
            return {
                "method": "one_candidate_stream",
                "complete_valid_ms": _elapsed_ms(started_ns),
                "first_text_ms": first_text_ms,
                "first_valid_json_ms": first_valid_json_ms,
                "candidate_count": len(parsed.candidates),
                "usage": _usage(completed),
            }
    finally:
        await client.aclose()


async def main() -> int:
    settings = Settings(_env_file=PROJECT_ROOT / "backend" / ".env")
    key = settings.gemini_key
    if key is None:
        print("Gemini is not configured; run configure-gemini.bat first.")
        return 2
    request = _request()
    runs: list[dict[str, Any]] = []
    for method, probe in (
        ("one_candidate_nonstream", probe_nonstream),
        ("one_candidate_stream", probe_stream),
    ):
        print(f"  {method}", flush=True)
        try:
            runs.append(await probe(
                request,
                api_key=key,
                model=settings.gemini_prediction_model,
                thinking_level=settings.gemini_prediction_thinking_level,
            ))
        except Exception as exc:
            # Never include the SDK exception body: it may contain conversation
            # data or server-provided text. Stop after the first failed call.
            category = "timeout" if isinstance(exc, TimeoutError) else "probe_failed"
            runs.append({"method": method, "error": category})
            break
    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "sdk": f"google-genai=={version('google-genai')}",
        "model": settings.gemini_prediction_model,
        "case_id": CASE_ID,
        "max_calls": 2,
        "actual_calls": len(runs),
        "max_candidates": 1,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
        "tools": False,
        "previous_interaction_id": False,
        "interpretation": (
            "A tiny controlled probe, not a general latency or accuracy estimate. "
            "First text and valid JSON timestamps are exploratory; only a "
            "completed and current provider result could become production ready. "
            "No model or runtime change is implied."
        ),
        "runs": runs,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized timings written to {RESULT_PATH}")
    return 0 if len(runs) == 2 and all("error" not in run for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
