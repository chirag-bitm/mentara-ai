"""Run the small, non-sensitive Milestone 4 Gemini answer benchmark."""

from __future__ import annotations

import asyncio
import json
import statistics
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
from uuid import UUID, uuid5


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_4_MODEL_BENCHMARK.json"

import sys

sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.services.answer.gemini import GeminiAnswerProvider  # noqa: E402
from app.services.answer.models import (  # noqa: E402
    AnswerContext,
    AnswerContextTurn,
    AnswerPrompt,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
    AnswerRequest,
)
from app.services.answer.policy import ConciseAnswerPolicy  # noqa: E402
from app.services.answer.provider import (  # noqa: E402
    AnswerProviderError,
    AnswerProviderRequest,
)
from app.services.conversation.models import (  # noqa: E402
    AssistanceKind,
    ContinuityQuality,
)
from app.services.transcript.models import SpeakerRole  # noqa: E402


SESSION_ID = UUID("40000000-0000-0000-0000-000000000001")
CANDIDATES = (
    {
        "model": "gemini-3.8-flash",
        "thinking_level": "low",
        "input_usd_per_million": 0.75,
        "output_usd_per_million": 3.75,
    },
    {
        "model": "gemini-3.5-flash-lite",
        "thinking_level": "minimal",
        "input_usd_per_million": 0.30,
        "output_usd_per_million": 2.50,
    },
)
CORPUS = (
    (
        "quick_factual",
        AssistanceKind.QUESTION,
        "What is the practical difference between a process and a thread?",
    ),
    (
        "technical_reasoning",
        AssistanceKind.REQUEST,
        "Explain why idempotency matters when retrying a payment API request.",
    ),
    (
        "speakable_guidance",
        AssistanceKind.REQUEST,
        "Give me a concise way to explain a project delay to a stakeholder.",
    ),
    (
        "missing_personal_context",
        AssistanceKind.QUESTION,
        "What measurable achievement did I deliver at my last employer?",
    ),
)


def _prompt(index: int, kind: AssistanceKind, text: str) -> AnswerPrompt:
    turn_id = uuid5(SESSION_ID, f"benchmark.turn.{index}")
    answer_id = uuid5(turn_id, "benchmark.answer")
    request = AnswerRequest(
        answer_id=answer_id,
        session_id=SESSION_ID,
        detection_id=uuid5(turn_id, "benchmark.detection"),
        source_turn_id=turn_id,
        source_turn_sequence=index,
        assistance_kind=kind,
        attempt=1,
        detected_ms=0,
        requested_ms=0,
        question_detected_to_answer_request_ms=0,
    )
    context = AnswerContext(
        session_id=SESSION_ID,
        answer_id=answer_id,
        assistance_kind=kind,
        source_turn=AnswerContextTurn(
            turn_id=turn_id,
            turn_sequence=index,
            speaker_role=SpeakerRole.LOCAL_USER,
            continuity_quality=ContinuityQuality.NORMAL,
            text=text,
        ),
        recent_turns=(),
        total_text_chars=len(text),
    )
    return ConciseAnswerPolicy().build_prompt(request, context)


def _elapsed_ms(start_ns: int) -> int:
    return round((perf_counter_ns() - start_ns) / 1_000_000)


def _estimated_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    candidate: dict[str, object],
) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    input_rate = float(candidate["input_usd_per_million"])
    output_rate = float(candidate["output_usd_per_million"])
    return round(
        (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000,
        8,
    )


async def _run_one(
    *,
    api_key: str,
    candidate: dict[str, object],
    prompt_id: str,
    prompt: AnswerPrompt,
    index: int,
) -> dict[str, object]:
    model = str(candidate["model"])
    thinking_level = str(candidate["thinking_level"])
    provider = GeminiAnswerProvider(
        api_key=api_key,
        model=model,
        thinking_level=thinking_level,
        max_output_tokens=256,
    )
    request = AnswerProviderRequest(
        answer_id=uuid5(SESSION_ID, f"benchmark.provider.{model}.{index}"),
        attempt=1,
        prompt=prompt,
    )
    started_ns = perf_counter_ns()
    first_text_ms: int | None = None
    text_parts: list[str] = []
    completion: AnswerProviderCompleted | None = None
    stream = None
    try:
        async with asyncio.timeout(30):
            stream = await provider.start(request)
            async for event in stream:
                if isinstance(event, AnswerProviderTextDelta):
                    text_parts.append(event.text)
                    if first_text_ms is None and event.text.strip():
                        first_text_ms = _elapsed_ms(started_ns)
                elif isinstance(event, AnswerProviderCompleted):
                    completion = event
                    break
        if completion is None:
            raise RuntimeError("provider stream ended without completion")
        usage = completion.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        return {
            "model": model,
            "thinking_level": thinking_level,
            "prompt_id": prompt_id,
            "first_useful_text_ms": first_text_ms,
            "total_generation_ms": _elapsed_ms(started_ns),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "estimated_paid_standard_cost_usd": _estimated_cost(
                input_tokens,
                output_tokens,
                candidate,
            ),
            "output": "".join(text_parts),
            "error": None,
            "human_review": {
                "relevance_1_to_5": None,
                "technical_quality_1_to_5": None,
                "speakability_1_to_5": None,
                "unnecessary_verbosity_1_to_5": None,
            },
        }
    except (AnswerProviderError, TimeoutError, RuntimeError) as exc:
        category = (
            exc.category.value
            if isinstance(exc, AnswerProviderError)
            else "benchmark_timeout"
            if isinstance(exc, TimeoutError)
            else "benchmark_protocol"
        )
        message = (
            exc.safe_message
            if isinstance(exc, AnswerProviderError)
            else "The benchmark request did not complete safely."
        )
        return {
            "model": model,
            "thinking_level": thinking_level,
            "prompt_id": prompt_id,
            "first_useful_text_ms": first_text_ms,
            "total_generation_ms": _elapsed_ms(started_ns),
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "estimated_paid_standard_cost_usd": None,
            "output": "".join(text_parts),
            "error": {
                "category": category,
                "message": message,
                "provider_http_status": (
                    exc.provider_status_code
                    if isinstance(exc, AnswerProviderError)
                    else None
                ),
            },
            "human_review": None,
        }
    finally:
        if stream is not None:
            with suppress(Exception):
                await stream.aclose()


def _median(values: list[int]) -> float | None:
    return statistics.median(values) if values else None


def _summaries(runs: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for candidate in CANDIDATES:
        model = candidate["model"]
        model_runs = [run for run in runs if run["model"] == model]
        successful = [run for run in model_runs if run["error"] is None]
        first_text = [
            int(run["first_useful_text_ms"])
            for run in successful
            if run["first_useful_text_ms"] is not None
        ]
        total = [int(run["total_generation_ms"]) for run in successful]
        costs = [
            float(run["estimated_paid_standard_cost_usd"])
            for run in successful
            if run["estimated_paid_standard_cost_usd"] is not None
        ]
        summaries.append(
            {
                "model": model,
                "thinking_level": candidate["thinking_level"],
                "successful_requests": len(successful),
                "request_count": len(model_runs),
                "median_first_useful_text_ms": _median(first_text),
                "median_total_generation_ms": _median(total),
                "estimated_paid_standard_cost_usd": round(sum(costs), 8),
            }
        )
    return summaries


async def main() -> int:
    settings = Settings(_env_file=BACKEND_ROOT / ".env")
    api_key = settings.gemini_key
    if api_key is None:
        print("Gemini is not configured. Run configure-gemini.bat first.")
        return 2

    print("Running 8 non-sensitive stateless benchmark requests...")
    runs: list[dict[str, object]] = []
    for index, (prompt_id, kind, text) in enumerate(CORPUS, start=1):
        prompt = _prompt(index, kind, text)
        for candidate in CANDIDATES:
            print(
                f"  {prompt_id}: {candidate['model']} "
                f"({candidate['thinking_level']})"
            )
            runs.append(
                await _run_one(
                    api_key=api_key,
                    candidate=candidate,
                    prompt_id=prompt_id,
                    prompt=prompt,
                    index=index,
                )
            )

    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "sdk": {"package": "google-genai", "version": version("google-genai")},
        "api": "Gemini Interactions API",
        "store": False,
        "tools": False,
        "previous_interaction_id": False,
        "corpus": [
            {"prompt_id": prompt_id, "assistance_kind": kind.value, "text": text}
            for prompt_id, kind, text in CORPUS
        ],
        "pricing_basis": {
            "as_of": "2026-09-12",
            "currency": "USD",
            "unit": "per 1M tokens",
            "source": "https://ai.google.dev/gemini-api/docs/pricing",
            "note": (
                "Approximate paid Standard pricing; free-tier calls may be free. "
                "Output pricing includes thinking tokens."
            ),
        },
        "runs": runs,
        "summaries": _summaries(runs),
        "interpretation_warning": (
            "This small benchmark informs a Mentara default; it does not establish "
            "general model superiority."
        ),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized results written to {RESULT_PATH}")
    for summary in result["summaries"]:
        print(
            f"  {summary['model']}: first text median="
            f"{summary['median_first_useful_text_ms']} ms, total median="
            f"{summary['median_total_generation_ms']} ms, successful="
            f"{summary['successful_requests']}/{summary['request_count']}"
        )
    return 0 if any(run["error"] is None for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
