"""Run the deterministic, offline M5.5 prediction pipeline evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from uuid import UUID, uuid5


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
CORPUS_PATH = (
    PROJECT_ROOT / "docs" / "MILESTONE_5_5_PREDICTION_EVALUATION_CORPUS.json"
)
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.conversation.identity import derive_turn_id  # noqa: E402
from app.services.conversation.models import (  # noqa: E402
    ActiveConversationTurn,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.memory import ConversationMemory  # noqa: E402
from app.services.prediction import (  # noqa: E402
    FakePredictionProvider,
    FakePredictionScript,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionInvalidationReason,
    PredictionProviderExecutor,
    PredictionProviderResult,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionState,
    PredictionTriggerPolicyLimits,
    DeterministicPredictionTriggerPolicy,
)
from app.services.transcript.models import (  # noqa: E402
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
)


NAMESPACE = UUID("70000000-0000-0000-0000-000000000001")
INPUT_USD_PER_MILLION = 0.30
OUTPUT_USD_PER_MILLION = 2.50


class ManualClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        return self.value


def _candidate(raw: dict[str, object]) -> PredictionCandidate:
    return PredictionCandidate(
        kind=PredictionCandidateKind(str(raw["kind"])),
        text=str(raw["text"]),
        anchor_terms=tuple(str(term) for term in raw.get("anchor_terms", [])),
    )


def _result(prefix: dict[str, object]) -> PredictionProviderResult:
    return PredictionProviderResult(
        candidates=tuple(
            _candidate(candidate)
            for candidate in prefix.get("candidates", [])
        ),
        finish_reason="offline_script",
    )


def _memory_turn(session_id: UUID, sequence: int, text: str) -> ConversationTurn:
    base_ms = sequence * 100
    return ConversationTurn(
        session_id=session_id,
        turn_id=derive_turn_id(session_id, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(uuid5(session_id, f"memory-utterance-{sequence}"),),
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


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


async def _evaluate_case(case: dict[str, object]) -> dict[str, object]:
    case_id = str(case["case_id"])
    session_id = uuid5(NAMESPACE, case_id)
    memory = ConversationMemory(session_id=session_id)
    memory_texts = [str(text) for text in case.get("memory", [])]
    for sequence, text in enumerate(memory_texts, start=1):
        memory.observe(_memory_turn(session_id, sequence, text))
    memory_before = memory.snapshot()

    prefixes = list(case["prefixes"])
    provider = FakePredictionProvider(
        [FakePredictionScript(result=_result(prefix)) for prefix in prefixes]
    )
    clock = ManualClock()
    executor = PredictionProviderExecutor(provider=provider, clock=clock)
    runtime = PredictionRuntime(
        session_id=session_id,
        executor=executor,
        clock=clock,
        limits=PredictionRuntimeLimits(
            coalesce_seconds=0,
            provider_timeout_seconds=1,
            max_attempts_per_turn=2,
            max_calls_per_session=2,
        ),
        trigger_policy=DeterministicPredictionTriggerPolicy(
            limits=PredictionTriggerPolicyLimits(min_call_interval_ms=0)
        ),
        memory_snapshot_supplier=memory.snapshot,
    )
    active_sequence = len(memory_texts) + 1
    turn_id = derive_turn_id(session_id, active_sequence)
    utterance_id = uuid5(session_id, "active-utterance")
    audio_source = AudioSource(str(case.get("audio_source", "microphone")))
    speaker_role = SpeakerRole(str(case.get("speaker_role", "local_user")))
    started_ms = max(0, int(prefixes[0]["observed_ms"]) - 500)
    ready_snapshots = []
    trigger_reasons: list[str] = []
    observe_overhead_ms: list[float] = []

    for revision, prefix in enumerate(prefixes, start=1):
        observed_ms = int(prefix["observed_ms"])
        clock.value = observed_ms
        awaiting = bool(prefix.get("awaiting_finalization", False))
        active = ActiveConversationTurn(
            session_id=session_id,
            turn_id=turn_id,
            turn_sequence=active_sequence,
            source_utterance_ids=(utterance_id,),
            source_transcript_sequences=(active_sequence,),
            audio_source=audio_source,
            speaker_role=speaker_role,
            text=str(prefix["text"]),
            started_ms=started_ms,
            last_updated_ms=observed_ms,
            continuity_quality=ContinuityQuality.NORMAL,
            awaiting_finalization=awaiting,
            pending_deadline_ms=observed_ms + 250 if awaiting else None,
        )
        utterance = CanonicalUtterance(
            session_id=session_id,
            utterance_id=utterance_id,
            sequence=active_sequence,
            revision=revision,
            audio_source=audio_source,
            speaker_role=speaker_role,
            text=active.text,
            is_final=bool(prefix.get("is_final", False)),
            first_seen_ms=started_ms,
            last_updated_ms=observed_ms,
            finalized_ms=observed_ms if prefix.get("is_final", False) else None,
        )
        started_ns = perf_counter_ns()
        submission = runtime.observe_nowait(
            active,
            utterance,
            memory_revision=memory_before.memory_revision,
        )
        observe_overhead_ms.append((perf_counter_ns() - started_ns) / 1_000_000)
        trigger_reasons.append(submission.trigger_reason.value)
        await runtime.wait_idle()
        current = runtime.snapshot().current
        if current is not None and current.state is PredictionState.READY:
            ready_snapshots.append(current)

    calls = len(provider.requests)
    latest_ready = ready_snapshots[-1] if ready_snapshots else None
    expected_anchors = {str(value).casefold() for value in case["expected_anchors"]}
    candidate_anchor_sets = (
        [
            {term.casefold() for term in candidate.anchor_terms}
            for candidate in latest_ready.candidates
        ]
        if latest_ready is not None
        else []
    )
    top1_useful = bool(
        candidate_anchor_sets
        and expected_anchors.intersection(candidate_anchor_sets[0])
    )
    topk_useful = any(
        expected_anchors.intersection(anchors) for anchors in candidate_anchor_sets
    )
    candidate_texts = [
        snapshot.candidates[0].text if snapshot.candidates else None
        for snapshot in ready_snapshots
    ]
    finalization_ms = int(prefixes[-1]["observed_ms"]) + 1_000
    lead_time_ms = (
        finalization_ms - latest_ready.ready_ms
        if latest_ready is not None and latest_ready.ready_ms is not None
        else None
    )
    prompt_chars = sum(
        len(request.prompt.system_instruction) + len(request.prompt.user_content)
        for request in provider.requests
    )
    output_chars = sum(
        len(candidate.text) + sum(len(term) for term in candidate.anchor_terms)
        for snapshot in ready_snapshots
        for candidate in snapshot.candidates
    )
    context_chars = [
        snapshot.context_chars
        for snapshot in ready_snapshots
        if snapshot.context_chars is not None
    ]
    memory_unchanged = memory.snapshot() == memory_before

    runtime.invalidate_turn_nowait(
        turn_id,
        reason=PredictionInvalidationReason.TURN_FINALIZED,
        at_ms=finalization_ms,
    )
    runtime.shutdown_nowait()
    await runtime.wait_idle()

    return {
        "case_id": case_id,
        "category": case["category"],
        "prediction_expected": bool(case["prediction_expected"]),
        "provider_calls": calls,
        "trigger_reasons": trigger_reasons,
        "top1_anchor_useful": top1_useful,
        "topk_anchor_useful": topk_useful,
        "ready_revision_count": len(ready_snapshots),
        "final_readiness": (
            latest_ready.readiness.value
            if latest_ready is not None and latest_ready.readiness is not None
            else None
        ),
        "candidate_change_observed": len(set(candidate_texts)) > 1,
        "consistent_revision_count": (
            latest_ready.candidate_consistent_revision_count
            if latest_ready is not None
            else 0
        ),
        "lead_time_before_final_ms": lead_time_ms,
        "max_context_chars": max(context_chars, default=0),
        "prompt_chars": prompt_chars,
        "output_chars": output_chars,
        "observe_overhead_ms": observe_overhead_ms,
        "max_active_provider_calls": provider.max_active_call_count,
        "memory_unchanged": memory_unchanged,
        "pending_tasks_after_cleanup": runtime.pending_task_count,
    }


async def _stale_race() -> dict[str, object]:
    session_id = uuid5(NAMESPACE, "stale-race")
    turn_id = derive_turn_id(session_id, 1)
    utterance_id = uuid5(session_id, "stale-race-utterance")
    gate = asyncio.Event()
    provider = FakePredictionProvider(
        [
            FakePredictionScript(
                result=PredictionProviderResult(
                    candidates=(
                        PredictionCandidate(
                            PredictionCandidateKind.QUESTION,
                            "Why Redis?",
                            ("redis",),
                        ),
                    )
                ),
                gate=gate,
                suppress_cancellation=True,
            ),
            FakePredictionScript(
                result=PredictionProviderResult(
                    candidates=(
                        PredictionCandidate(
                            PredictionCandidateKind.QUESTION,
                            "Why DynamoDB?",
                            ("dynamodb",),
                        ),
                    )
                )
            ),
        ]
    )
    clock = ManualClock()
    executor = PredictionProviderExecutor(provider=provider, clock=clock)
    runtime = PredictionRuntime(
        session_id=session_id,
        executor=executor,
        clock=clock,
        limits=PredictionRuntimeLimits(0, 1, 2, 2),
        trigger_policy=DeterministicPredictionTriggerPolicy(
            limits=PredictionTriggerPolicyLimits(min_call_interval_ms=0)
        ),
    )

    def inputs(text: str, revision: int, at_ms: int):
        active = ActiveConversationTurn(
            session_id=session_id,
            turn_id=turn_id,
            turn_sequence=1,
            source_utterance_ids=(utterance_id,),
            source_transcript_sequences=(1,),
            audio_source=AudioSource.MICROPHONE,
            speaker_role=SpeakerRole.LOCAL_USER,
            text=text,
            started_ms=500,
            last_updated_ms=at_ms,
            continuity_quality=ContinuityQuality.NORMAL,
            awaiting_finalization=False,
            pending_deadline_ms=None,
        )
        utterance = CanonicalUtterance(
            session_id=session_id,
            utterance_id=utterance_id,
            sequence=1,
            revision=revision,
            audio_source=AudioSource.MICROPHONE,
            speaker_role=SpeakerRole.LOCAL_USER,
            text=text,
            is_final=False,
            first_seen_ms=500,
            last_updated_ms=at_ms,
        )
        return active, utterance

    clock.value = 1_000
    active, utterance = inputs("You mentioned Redis in your architecture", 1, 1_000)
    runtime.observe_nowait(active, utterance, memory_revision=0)
    for _ in range(100):
        if provider.requests:
            break
        await asyncio.sleep(0)
    clock.value = 1_200
    active, utterance = inputs(
        "Correction, you mentioned DynamoDB in your architecture",
        2,
        1_200,
    )
    runtime.observe_nowait(active, utterance, memory_revision=0)
    await runtime.wait_idle()
    snapshot = runtime.snapshot()
    current = snapshot.current
    result = {
        "provider_calls": len(provider.requests),
        "cancelled_calls": provider.cancelled_call_count,
        "stale_discard_count": snapshot.stale_discard_count,
        "latest_candidate": (
            current.candidates[0].text
            if current is not None and current.candidates
            else None
        ),
        "max_active_provider_calls": provider.max_active_call_count,
    }
    runtime.shutdown_nowait()
    await runtime.wait_idle()
    result["pending_tasks_after_cleanup"] = runtime.pending_task_count
    return result


async def run_evaluation() -> dict[str, object]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    cases = [await _evaluate_case(case) for case in corpus["cases"]]
    stale = await _stale_race()
    expected = [case for case in cases if case["prediction_expected"]]
    suppressed = [case for case in cases if not case["prediction_expected"]]
    observe_values = [
        value for case in cases for value in case["observe_overhead_ms"]
    ]
    lead_values = [
        int(case["lead_time_before_final_ms"])
        for case in expected
        if case["lead_time_before_final_ms"] is not None
    ]
    input_token_proxy = sum(int(case["prompt_chars"]) for case in cases) // 4
    output_token_proxy = sum(int(case["output_chars"]) for case in cases) // 4
    estimated_cost = (
        input_token_proxy * INPUT_USD_PER_MILLION
        + output_token_proxy * OUTPUT_USD_PER_MILLION
    ) / 1_000_000
    consistent_checks = [
        case
        for case, definition in zip(cases, corpus["cases"], strict=True)
        if definition.get("consistent_candidate_expected")
    ]
    change_checks = [
        case
        for case, definition in zip(cases, corpus["cases"], strict=True)
        if definition.get("candidate_change_expected")
    ]
    checks = {
        "expected_cases_produced_prediction": all(
            case["provider_calls"] >= 1 and case["ready_revision_count"] >= 1
            for case in expected
        ),
        "suppressed_cases_made_no_calls": all(
            case["provider_calls"] == 0 for case in suppressed
        ),
        "top_k_anchor_useful_for_expected_cases": all(
            case["topk_anchor_useful"] for case in expected
        ),
        "stable_requires_repeat_and_finalization_signal": all(
            case["consistent_revision_count"] >= 2
            and case["final_readiness"] == "stable"
            for case in consistent_checks
        ),
        "topic_changes_replace_candidates": all(
            case["candidate_change_observed"] for case in change_checks
        ),
        "stale_completion_rejected": (
            stale["stale_discard_count"] >= 1
            and stale["latest_candidate"] == "Why DynamoDB?"
        ),
        "one_active_provider_call_per_turn": all(
            case["max_active_provider_calls"] <= 1 for case in cases
        )
        and stale["max_active_provider_calls"] <= 1,
        "hard_turn_call_ceiling_respected": all(
            case["provider_calls"] <= 2 for case in cases
        ),
        "context_bound_respected": all(
            case["max_context_chars"] <= 3_200 for case in cases
        ),
        "prediction_did_not_mutate_memory": all(
            case["memory_unchanged"] for case in cases
        ),
        "cleanup_left_no_tasks": all(
            case["pending_tasks_after_cleanup"] == 0 for case in cases
        )
        and stale["pending_tasks_after_cleanup"] == 0,
        "ready_preceded_finalization": all(value > 0 for value in lead_values),
    }
    return {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "evaluation_kind": "offline_deterministic_fake_provider_pipeline",
        "corpus_file": CORPUS_PATH.name,
        "corpus_case_count": len(cases),
        "interpretation_warning": (
            "This measures deterministic Mentara trigger, context, lifecycle, and "
            "race behavior on a small named corpus. Scripted candidates must not be "
            "described as general model prediction accuracy."
        ),
        "quality": {
            "prediction_expected_cases": len(expected),
            "suppression_expected_cases": len(suppressed),
            "unnecessary_prediction_case_rate": round(
                sum(case["provider_calls"] > 0 for case in suppressed)
                / max(1, len(suppressed)),
                4,
            ),
            "top1_anchor_usefulness_rate": round(
                sum(case["top1_anchor_useful"] for case in expected)
                / max(1, len(expected)),
                4,
            ),
            "topk_anchor_usefulness_rate": round(
                sum(case["topk_anchor_useful"] for case in expected)
                / max(1, len(expected)),
                4,
            ),
        },
        "calls": {
            "total_provider_calls": sum(int(case["provider_calls"]) for case in cases),
            "mean_calls_per_turn": round(
                statistics.mean(int(case["provider_calls"]) for case in cases),
                4,
            ),
            "max_calls_for_one_turn": max(
                int(case["provider_calls"]) for case in cases
            ),
        },
        "lead_time_ms": {
            "count": len(lead_values),
            "median": statistics.median(lead_values),
            "minimum": min(lead_values),
            "maximum": max(lead_values),
        },
        "local_observation_overhead_ms": {
            "count": len(observe_values),
            "median": round(statistics.median(observe_values), 4),
            "p95": round(_percentile(observe_values, 0.95), 4),
            "maximum": round(max(observe_values), 4),
        },
        "context": {
            "maximum_selected_chars": max(
                int(case["max_context_chars"]) for case in cases
            ),
            "configured_max_chars": 3_200,
        },
        "cost_proxy": {
            "method": "ceil-like characters/4 proxy; not provider token accounting",
            "input_token_proxy": input_token_proxy,
            "output_token_proxy": output_token_proxy,
            "gemini_3_5_flash_lite_standard_usd_per_million_input": (
                INPUT_USD_PER_MILLION
            ),
            "gemini_3_5_flash_lite_standard_usd_per_million_output": (
                OUTPUT_USD_PER_MILLION
            ),
            "estimated_corpus_cost_usd": round(estimated_cost, 8),
            "pricing_as_of": "2026-09-13",
            "pricing_source": "https://ai.google.dev/gemini-api/docs/pricing",
        },
        "stale_race": stale,
        "cases": cases,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT / "docs" / "MILESTONE_5_5_PREDICTION_EVALUATION.json"
        ),
    )
    args = parser.parse_args()
    result = asyncio.run(run_evaluation())
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

