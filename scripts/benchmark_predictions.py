"""Run a tiny non-sensitive Gemini M5.5 prediction benchmark."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter_ns
from uuid import UUID, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
CORPUS_PATH = (
    PROJECT_ROOT / "docs" / "MILESTONE_5_5_PREDICTION_EVALUATION_CORPUS.json"
)
RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_5_5_MODEL_BENCHMARK.json"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.services.conversation.identity import derive_turn_id  # noqa: E402
from app.services.conversation.models import (  # noqa: E402
    ActiveConversationTurn,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.memory import ConversationMemory  # noqa: E402
from app.services.prediction import (  # noqa: E402
    DeterministicPredictionContextPlanner,
    DeterministicPredictionTriggerPolicy,
    GeminiPredictionProvider,
    LikelyNextTurnPolicy,
    PredictionProviderError,
    PredictionProviderRequest,
    PredictionTriggerPolicyLimits,
    build_prediction_request,
)
from app.services.transcript.models import (  # noqa: E402
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
)


NAMESPACE = UUID("71000000-0000-0000-0000-000000000001")
CASE_IDS = {
    "technical_follow_up",
    "behavioral_follow_up",
    "topic_return",
    "ordinary_statement",
    "hinglish_follow_up",
}
INPUT_USD_PER_MILLION = 0.30
OUTPUT_USD_PER_MILLION = 2.50


def _memory_turn(session_id: UUID, sequence: int, text: str) -> ConversationTurn:
    base_ms = sequence * 100
    return ConversationTurn(
        session_id=session_id,
        turn_id=derive_turn_id(session_id, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(uuid5(session_id, f"memory-{sequence}"),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=base_ms,
        last_updated_ms=base_ms + 20,
        source_finalized_ms=base_ms + 20,
        finalized_ms=base_ms + 25,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=5,
    )


def _inputs(case: dict[str, object], index: int):
    session_id = uuid5(NAMESPACE, str(case["case_id"]))
    memory = ConversationMemory(session_id=session_id)
    memory_texts = [str(text) for text in case.get("memory", [])]
    for sequence, text in enumerate(memory_texts, start=1):
        memory.observe(_memory_turn(session_id, sequence, text))
    prefix = list(case["prefixes"])[-1]
    observed_ms = int(prefix["observed_ms"])
    turn_sequence = len(memory_texts) + 1
    turn_id = derive_turn_id(session_id, turn_sequence)
    utterance_id = uuid5(session_id, "active")
    awaiting = bool(prefix.get("awaiting_finalization", False))
    source = AudioSource(str(case.get("audio_source", "microphone")))
    speaker = SpeakerRole(str(case.get("speaker_role", "local_user")))
    active = ActiveConversationTurn(
        session_id=session_id,
        turn_id=turn_id,
        turn_sequence=turn_sequence,
        source_utterance_ids=(utterance_id,),
        source_transcript_sequences=(turn_sequence,),
        audio_source=source,
        speaker_role=speaker,
        text=str(prefix["text"]),
        started_ms=max(0, observed_ms - 500),
        last_updated_ms=observed_ms,
        continuity_quality=ContinuityQuality.NORMAL,
        awaiting_finalization=awaiting,
        pending_deadline_ms=observed_ms + 250 if awaiting else None,
    )
    utterance = CanonicalUtterance(
        session_id=session_id,
        utterance_id=utterance_id,
        sequence=turn_sequence,
        revision=index,
        audio_source=source,
        speaker_role=speaker,
        text=active.text,
        is_final=bool(prefix.get("is_final", False)),
        first_seen_ms=active.started_ms,
        last_updated_ms=observed_ms,
        finalized_ms=observed_ms if prefix.get("is_final", False) else None,
    )
    return memory.snapshot(), active, utterance


def _provider_request(case: dict[str, object], index: int, max_output_tokens: int):
    snapshot, active, utterance = _inputs(case, index)
    trigger = DeterministicPredictionTriggerPolicy(
        limits=PredictionTriggerPolicyLimits(min_call_interval_ms=0)
    ).evaluate(
        active,
        utterance,
        observed_ms=active.last_updated_ms,
        last_attempt_started_ms=None,
    )
    if not trigger.eligible:
        return trigger, None
    context = DeterministicPredictionContextPlanner().plan(
        snapshot,
        active,
        input_revision=1,
    )
    request = build_prediction_request(
        active,
        utterance,
        context,
        input_revision=1,
        attempt=1,
        input_observed_ms=active.last_updated_ms,
        requested_ms=active.last_updated_ms,
    )
    return trigger, PredictionProviderRequest(
        prediction_id=request.prediction_id,
        input_revision=1,
        attempt=1,
        prompt=LikelyNextTurnPolicy().build_prompt(request),
        max_candidates=3,
        max_output_tokens=max_output_tokens,
    )


async def _run_case(provider, case: dict[str, object], index: int, max_output_tokens: int):
    trigger, request = _provider_request(case, index, max_output_tokens)
    if request is None:
        return {
            "case_id": case["case_id"],
            "provider_called": False,
            "trigger_reason": trigger.reason.value,
            "latency_ms": None,
            "lead_time_before_final_ms": None,
            "candidate_count": 0,
            "candidates": [],
            "top1_anchor_useful": False,
            "topk_anchor_useful": False,
            "input_tokens": None,
            "output_tokens": None,
            "billed_output_token_proxy": None,
            "total_tokens": None,
            "estimated_cost_usd": 0.0,
            "error": None,
        }
    started_ns = perf_counter_ns()
    try:
        async with asyncio.timeout(15):
            result = await provider.predict(request)
        latency_ms = round((perf_counter_ns() - started_ns) / 1_000_000)
        expected = {str(anchor).casefold() for anchor in case["expected_anchors"]}
        anchors = [
            {term.casefold() for term in candidate.anchor_terms}
            for candidate in result.candidates
        ]
        usage = result.usage
        input_tokens = usage.input_tokens if usage is not None else None
        output_tokens = usage.output_tokens if usage is not None else None
        # total minus input includes visible output plus billed thought tokens.
        # No tools are enabled for these requests.
        billed_output_proxy = (
            usage.total_tokens - input_tokens
            if usage is not None
            and usage.total_tokens is not None
            and input_tokens is not None
            and usage.total_tokens >= input_tokens
            else None
        )
        cost = (
            (
                input_tokens * INPUT_USD_PER_MILLION
                + billed_output_proxy * OUTPUT_USD_PER_MILLION
            )
            / 1_000_000
            if input_tokens is not None and billed_output_proxy is not None
            else None
        )
        return {
            "case_id": case["case_id"],
            "provider_called": True,
            "trigger_reason": trigger.reason.value,
            "latency_ms": latency_ms,
            "lead_time_before_final_ms": 4_000 - latency_ms,
            "candidate_count": len(result.candidates),
            "candidates": [
                {
                    "kind": candidate.kind.value,
                    "text": candidate.text,
                    "anchor_terms": list(candidate.anchor_terms),
                }
                for candidate in result.candidates
            ],
            "top1_anchor_useful": bool(anchors and expected.intersection(anchors[0])),
            "topk_anchor_useful": any(expected.intersection(item) for item in anchors),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "billed_output_token_proxy": billed_output_proxy,
            "total_tokens": usage.total_tokens if usage is not None else None,
            "estimated_cost_usd": round(cost, 8) if cost is not None else None,
            "error": None,
        }
    except (PredictionProviderError, TimeoutError) as exc:
        return {
            "case_id": case["case_id"],
            "provider_called": True,
            "trigger_reason": trigger.reason.value,
            "latency_ms": round((perf_counter_ns() - started_ns) / 1_000_000),
            "lead_time_before_final_ms": None,
            "candidate_count": 0,
            "candidates": [],
            "top1_anchor_useful": False,
            "topk_anchor_useful": False,
            "input_tokens": None,
            "output_tokens": None,
            "billed_output_token_proxy": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
            "error": {
                "category": (
                    exc.category.value
                    if isinstance(exc, PredictionProviderError)
                    else "benchmark_timeout"
                ),
                "message": (
                    exc.safe_message
                    if isinstance(exc, PredictionProviderError)
                    else "The prediction benchmark request timed out."
                ),
                "provider_reason": (
                    exc.provider_reason
                    if isinstance(exc, PredictionProviderError)
                    else None
                ),
            },
        }


async def main() -> int:
    settings = Settings(_env_file=BACKEND_ROOT / ".env")
    api_key = settings.gemini_key
    if api_key is None:
        print("Gemini is not configured. Run configure-gemini.bat first.")
        return 2
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    cases = [case for case in corpus["cases"] if case["case_id"] in CASE_IDS]
    provider = GeminiPredictionProvider(
        api_key=api_key,
        model=settings.gemini_prediction_model,
        thinking_level=settings.gemini_prediction_thinking_level,
    )
    print("Running at most four non-sensitive stateless prediction requests...")
    runs = []
    aborted = []
    for index, case in enumerate(cases, start=1):
        print(f"  {case['case_id']}")
        run = await _run_case(
            provider, case, index, settings.prediction_max_output_tokens
        )
        runs.append(run)
        if run["provider_called"] and run["error"] is not None:
            # A single failed probe is enough diagnostic evidence. Do not
            # spend three more calls on the same model/configuration.
            aborted = [remaining["case_id"] for remaining in cases[index:]]
            break
    called = [run for run in runs if run["provider_called"]]
    successful = [run for run in called if run["error"] is None]
    latencies = [int(run["latency_ms"]) for run in successful]
    costs = [
        float(run["estimated_cost_usd"])
        for run in called
        if run["estimated_cost_usd"] is not None
    ]
    costs_complete = all(run["estimated_cost_usd"] is not None for run in called)
    expected_calls = sum(
        _provider_request(case, index, settings.prediction_max_output_tokens)[1]
        is not None
        for index, case in enumerate(cases, start=1)
    )
    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "sdk": {"package": "google-genai", "version": version("google-genai")},
        "api": "Gemini Interactions API",
        "model": settings.gemini_prediction_model,
        "thinking_level": settings.gemini_prediction_thinking_level,
        "max_output_tokens": settings.prediction_max_output_tokens,
        "store": False,
        "tools": False,
        "previous_interaction_id": False,
        "request_count": len(called),
        "planned_request_count": expected_calls,
        "suppressed_case_count": len(runs) - len(called),
        "aborted_case_ids": aborted,
        "successful_request_count": len(successful),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "top1_anchor_usefulness_rate": (
            round(sum(run["top1_anchor_useful"] for run in successful) / len(successful), 4)
            if successful
            else None
        ),
        "topk_anchor_usefulness_rate": (
            round(sum(run["topk_anchor_useful"] for run in successful) / len(successful), 4)
            if successful
            else None
        ),
        "estimated_total_cost_usd": (
            round(sum(costs), 8) if costs_complete else None
        ),
        "pricing_basis": {
            "as_of": "2026-09-19",
            "input_usd_per_million_tokens": INPUT_USD_PER_MILLION,
            "output_usd_per_million_tokens": OUTPUT_USD_PER_MILLION,
            "source": "https://ai.google.dev/gemini-api/docs/pricing",
        },
        "runs": runs,
        "interpretation_warning": (
            "This tiny controlled benchmark informs Mentara configuration only; "
            "it does not establish general prediction accuracy."
        ),
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized results written to {RESULT_PATH}")
    return 0 if len(successful) == expected_calls == 4 and not aborted else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
