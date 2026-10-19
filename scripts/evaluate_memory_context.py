"""Run the deterministic, offline Milestone 5 memory/context evaluation."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.conversation.identity import derive_turn_id  # noqa: E402
from app.services.conversation.models import (  # noqa: E402
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.memory import (  # noqa: E402
    ContextPlannerLimits,
    ConversationMemory,
    DeterministicContextPlanner,
    MemoryLimits,
)
from app.services.transcript.models import AudioSource, SpeakerRole  # noqa: E402


SESSION_ID = UUID("50000000-0000-0000-0000-000000000001")


def _turn(sequence: int, text: str) -> ConversationTurn:
    base_ms = sequence * 24_000
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=base_ms,
        last_updated_ms=base_ms + 500,
        source_finalized_ms=base_ms + 500,
        finalized_ms=base_ms + 510,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=10,
    )


def _long_session_text(sequence: int) -> str:
    if sequence == 100:
        return "We chose Redis as the caching layer for low-latency session reads."
    if sequence == 180:
        return "PostgreSQL stores durable account records and transaction metadata."
    if sequence == 300:
        return "Coming back to Redis, why not use DynamoDB for the cache?"
    return (
        f"Discussion item {sequence} covers routine planning, delivery status, "
        "team coordination, and the next scheduled review."
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_evaluation() -> dict[str, object]:
    limits = MemoryLimits()
    planner_limits = ContextPlannerLimits()
    memory = ConversationMemory(session_id=SESSION_ID, limits=limits)
    observe_ms: list[float] = []
    for sequence in range(1, 301):
        started = perf_counter_ns()
        memory.observe(_turn(sequence, _long_session_text(sequence)))
        observe_ms.append((perf_counter_ns() - started) / 1_000_000)

    snapshot = memory.snapshot()
    planner = DeterministicContextPlanner(limits=planner_limits)
    source = snapshot.entries[-1]
    assembly_ms: list[float] = []
    plan = None
    for _ in range(1_000):
        started = perf_counter_ns()
        plan = planner.plan(snapshot, source_turn_id=source.turn_id)
        assembly_ms.append((perf_counter_ns() - started) / 1_000_000)
    assert plan is not None

    character_pressure = ConversationMemory(session_id=SESSION_ID, limits=limits)
    for sequence in range(1, 301):
        character_pressure.observe(_turn(sequence, f"{sequence:04d}-" + "x" * 995))
    pressure_snapshot = character_pressure.snapshot()

    follow_up_memory = ConversationMemory(session_id=SESSION_ID)
    follow_up_memory.observe(_turn(1, "We use Redis as our caching layer."))
    follow_up_memory.observe(_turn(2, "Why?"))
    follow_up_snapshot = follow_up_memory.snapshot()
    follow_up_plan = planner.plan(
        follow_up_snapshot,
        source_turn_id=follow_up_snapshot.entries[-1].turn_id,
    )

    selected_relevant = [turn.turn_sequence for turn in plan.relevant_older_turns]
    full_chars = snapshot.stored_text_chars
    context_chars = plan.total_text_chars
    approx_context_tokens = (context_chars + 3) // 4
    approx_full_tokens = (full_chars + 3) // 4

    checks = {
        "turn_bound_respected": snapshot.stored_turn_count <= limits.max_retained_turns,
        "character_bound_respected": (
            pressure_snapshot.stored_text_chars <= limits.max_retained_text_chars
        ),
        "context_bound_respected": (
            context_chars <= planner_limits.max_total_text_chars
        ),
        "short_follow_up_has_recent_context": (
            [turn.turn_sequence for turn in follow_up_plan.recent_turns] == [1]
        ),
        "long_range_named_topic_selected": 100 in selected_relevant,
        "eviction_reported_as_degraded": (
            snapshot.evicted_turn_count == 44
            and snapshot.continuity.value == "degraded"
        ),
    }

    return {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "evaluation_kind": "offline_deterministic_no_provider_calls",
        "configuration": {
            "memory": {
                "max_retained_turns": limits.max_retained_turns,
                "max_retained_text_chars": limits.max_retained_text_chars,
                "max_entry_text_chars": limits.max_entry_text_chars,
            },
            "context": {
                "max_recent_turns": planner_limits.max_recent_turns,
                "max_relevant_older_turns": (
                    planner_limits.max_relevant_older_turns
                ),
                "max_total_text_chars": planner_limits.max_total_text_chars,
                "max_turn_text_chars": planner_limits.max_turn_text_chars,
            },
        },
        "fixed_corpus": {
            "turn_count": 300,
            "simulated_session_minutes": 120,
            "retained_turn_count": snapshot.stored_turn_count,
            "retained_text_chars": snapshot.stored_text_chars,
            "evicted_turn_count": snapshot.evicted_turn_count,
            "memory_revision": snapshot.memory_revision,
            "continuity": snapshot.continuity.value,
        },
        "character_pressure_corpus": {
            "turn_count": 300,
            "retained_turn_count": pressure_snapshot.stored_turn_count,
            "retained_text_chars": pressure_snapshot.stored_text_chars,
            "evicted_turn_count": pressure_snapshot.evicted_turn_count,
        },
        "selection": {
            "source_turn_sequence": plan.source_turn.turn_sequence,
            "recent_turn_sequences": [
                turn.turn_sequence for turn in plan.recent_turns
            ],
            "relevant_older_turn_sequences": selected_relevant,
            "context_text_chars": context_chars,
            "retained_to_context_char_ratio": round(full_chars / context_chars, 3),
        },
        "input_growth_proxy": {
            "method": "ceil(text_characters/4); not a provider token count",
            "retained_memory_approx_tokens": approx_full_tokens,
            "selected_context_approx_tokens": approx_context_tokens,
            "selected_fraction": round(context_chars / full_chars, 6),
        },
        "local_latency_ms": {
            "observe_count": len(observe_ms),
            "observe_median": round(statistics.median(observe_ms), 4),
            "observe_p95": round(_percentile(observe_ms, 0.95), 4),
            "observe_max": round(max(observe_ms), 4),
            "assembly_count": len(assembly_ms),
            "assembly_median": round(statistics.median(assembly_ms), 4),
            "assembly_p95": round(_percentile(assembly_ms, 0.95), 4),
            "assembly_max": round(max(assembly_ms), 4),
        },
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "summary_compaction_decision": {
            "choice": "A_deterministic_memory_sufficient_for_M5",
            "reason": (
                "The bounded recent/relevant planner passes the controlled M5 "
                "follow-up and topic-return checks with negligible local latency "
                "and no extra API call. Derived summarization remains a future "
                "provider-neutral hook and is not justified for M5."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs" / "MILESTONE_5_MEMORY_EVALUATION.json",
    )
    args = parser.parse_args()
    result = run_evaluation()
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
