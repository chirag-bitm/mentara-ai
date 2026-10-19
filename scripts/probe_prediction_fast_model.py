"""Single-call, non-sensitive model-latency comparison; not a runtime adapter.

The supported Gemini 2.5 Flash-Lite model has thinking off by default in the
Interactions API. Never save the prompt, candidate, provider errors, or key.
"""

from __future__ import annotations

import asyncio
import json
import sys
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
from app.services.prediction.gemini import _GeminiPredictionOutput  # noqa: E402
from scripts.probe_prediction_latency import (  # noqa: E402
    CASE_ID,
    MAX_OUTPUT_TOKENS,
    TIMEOUT_SECONDS,
    _nonnegative_int,
    _request,
)


RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_5_5_FAST_MODEL_PROBE.json"
MODEL = "gemini-2.5-flash-lite"
MAX_RESPONSE_CHARS = 4_096


async def probe_one_request(
    *,
    api_key: str,
    client_factory: Callable[..., Any] = genai.Client,
) -> dict[str, object]:
    request = _request()
    schema = _GeminiPredictionOutput.model_json_schema()
    schema["properties"]["candidates"]["maxItems"] = 1
    async_client: Any = None
    started_ns = perf_counter_ns()
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async_client = client_factory(
                api_key=api_key,
                http_options={"retry_options": {"attempts": 0}},
            ).aio
            interaction = await async_client.interactions.create(
                model=MODEL,
                input=[{
                    "type": "user_input",
                    "content": [{"type": "text", "text": request.prompt.user_content}],
                }],
                system_instruction=request.prompt.system_instruction,
                # 2.5 Flash-Lite defaults to thinking off. `thinking_level`
                # "minimal" is specific to 3.x and cannot be sent here.
                generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS},
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": schema,
                },
                stream=False,
                store=False,
            )
            if getattr(interaction, "status", None) != "completed":
                raise ValueError("The model interaction was not completed")
            output_text = getattr(interaction, "output_text", None)
            if (
                not isinstance(output_text, str)
                or len(output_text) > MAX_RESPONSE_CHARS
            ):
                raise ValueError("The model response did not fit the bound")
            parsed = _GeminiPredictionOutput.model_validate_json(output_text)
            if len(parsed.candidates) != 1:
                raise ValueError("The model did not return one valid candidate")
            usage = getattr(interaction, "usage", None)
            anchor_terms = {a.casefold() for a in parsed.candidates[0].anchor_terms}
            # This fixed non-sensitive technical example only tests whether
            # the output stays on the known topic, not general usefulness.
            return {
                "complete_valid_ms": round(
                    (perf_counter_ns() - started_ns) / 1_000_000
                ),
                "candidate_count": 1,
                "fixed_case_redis_anchor_present": "redis" in anchor_terms,
                "usage": {
                    "input_tokens": _nonnegative_int(
                        getattr(usage, "total_input_tokens", None)
                    ),
                    "output_tokens": _nonnegative_int(
                        getattr(usage, "total_output_tokens", None)
                    ),
                    "total_tokens": _nonnegative_int(
                        getattr(usage, "total_tokens", None)
                    ),
                },
            }
    finally:
        if async_client is not None:
            await async_client.aclose()


async def main() -> int:
    settings = Settings(_env_file=PROJECT_ROOT / "backend" / ".env")
    key = settings.gemini_key
    if key is None:
        print("Gemini is not configured; run configure-gemini.bat first.")
        return 2
    print(f"  one bounded {MODEL} request", flush=True)
    try:
        run = await probe_one_request(api_key=key)
    except Exception as exc:
        # Never serialize exception text; the SDK response might contain
        # private content. No automatic retry and no second paid call.
        run = {"error": "timeout" if isinstance(exc, TimeoutError) else "probe_failed"}
    report = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "sdk": f"google-genai=={version('google-genai')}",
        "model": MODEL,
        "case_id": CASE_ID,
        "max_calls": 1,
        "actual_calls": 1,
        "max_candidates": 1,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "thinking": "default_off",
        "store": False,
        "tools": False,
        "previous_interaction_id": False,
        "interpretation": (
            "One non-sensitive sample only; compare completed-result latency, "
            "not first-token time. No live-speaker usefulness or general "
            "prediction accuracy is established; no production change."
        ),
        "run": run,
    }
    RESULT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized timings written to {RESULT_PATH}")
    return 0 if "error" not in run else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
