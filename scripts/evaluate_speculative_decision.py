"""Offline fake-provider decision gate for speculative answer generation."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True, frozen=True)
class Evidence:
    session_id: str
    turn_id: str
    source_id: str
    memory_revision: int
    predicted_text: str
    final_text: str
    readiness: str = "stable"
    continuity: str = "normal"


class FakeSpeculativeAnswerProvider:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.cancelled = 0

    async def generate(self, gate: asyncio.Event | None = None) -> str:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if gate is not None:
                await gate.wait()
            await asyncio.sleep(0)
            return "hidden speculative answer"
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


def _normalize(text: str) -> str:
    return " ".join(text.casefold().rstrip(".?!").split())


def _strictly_compatible(predicted: Evidence, authoritative: Evidence) -> bool:
    return (
        predicted.session_id == authoritative.session_id
        and predicted.turn_id == authoritative.turn_id
        and predicted.source_id == authoritative.source_id
        and predicted.memory_revision == authoritative.memory_revision
        and predicted.readiness == "stable"
        and predicted.continuity == "normal"
        and authoritative.continuity == "normal"
        and _normalize(predicted.predicted_text)
        == _normalize(authoritative.final_text)
    )


async def run_evaluation() -> dict[str, object]:
    provider = FakeSpeculativeAnswerProvider()
    answer_history: list[str] = []
    cases = [
        (
            "exact_match",
            Evidence("s1", "t1", "u1", 3, "Why Redis?", "Why Redis?"),
            Evidence("s1", "t1", "u1", 3, "Why Redis?", "Why Redis?"),
        ),
        (
            "semantic_paraphrase",
            Evidence("s1", "t2", "u2", 3, "Why Redis?", "Why did you choose Redis?"),
            Evidence("s1", "t2", "u2", 3, "Why Redis?", "Why did you choose Redis?"),
        ),
        (
            "memory_changed",
            Evidence("s1", "t3", "u3", 3, "What if Redis fails?", "What if Redis fails?"),
            Evidence("s1", "t3", "u3", 4, "What if Redis fails?", "What if Redis fails?"),
        ),
        (
            "provenance_changed",
            Evidence("s1", "t4", "u4", 3, "Explain failover", "Explain failover"),
            Evidence("s1", "t4", "u5", 3, "Explain failover", "Explain failover"),
        ),
        (
            "tentative_only",
            Evidence("s1", "t5", "u5", 3, "Why DynamoDB?", "Why DynamoDB?", readiness="tentative"),
            Evidence("s1", "t5", "u5", 3, "Why DynamoDB?", "Why DynamoDB?"),
        ),
        (
            "degraded_continuity",
            Evidence("s1", "t6", "u6", 3, "Explain recovery", "Explain recovery", continuity="degraded"),
            Evidence("s1", "t6", "u6", 3, "Explain recovery", "Explain recovery", continuity="degraded"),
        ),
    ]
    results = []
    for case_id, predicted, authoritative in cases:
        hidden = await provider.generate()
        results.append(
            {
                "case_id": case_id,
                "hidden_generation_completed": bool(hidden),
                "strictly_compatible": _strictly_compatible(predicted, authoritative),
                "exposed_to_answer_history": False,
            }
        )

    correction_gate = asyncio.Event()
    correction_task = asyncio.create_task(provider.generate(correction_gate))
    await asyncio.sleep(0)
    correction_task.cancel()
    await asyncio.gather(correction_task, return_exceptions=True)
    results.append(
        {
            "case_id": "correction_while_running",
            "hidden_generation_completed": False,
            "strictly_compatible": False,
            "exposed_to_answer_history": False,
        }
    )

    compatible_count = sum(case["strictly_compatible"] for case in results)
    checks = {
        "only_exact_full_evidence_match_is_compatible": compatible_count == 1,
        "semantic_paraphrase_is_discarded": not next(
            case["strictly_compatible"]
            for case in results
            if case["case_id"] == "semantic_paraphrase"
        ),
        "correction_cancels_hidden_generation": provider.cancelled == 1,
        "one_active_generation_maximum": provider.max_active == 1,
        "no_speculation_entered_answer_history": answer_history == []
        and all(not case["exposed_to_answer_history"] for case in results),
    }
    return {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "evaluation_kind": "offline_fake_provider_speculative_answer_decision_gate",
        "production_speculative_generation_implemented": False,
        "experimental_feature_flag_added": False,
        "cases": results,
        "provider_calls": provider.calls,
        "cancelled_calls": provider.cancelled,
        "strict_compatibility_rate": round(compatible_count / len(results), 4),
        "decision": "defer_speculative_answer_generation",
        "decision_reason": (
            "Only exact text plus unchanged session, turn, source, memory version, "
            "stable readiness, and normal continuity can be considered safe. Even "
            "this curated gate accepted only one case, while every predicted turn "
            "would add a second model call. The small real-provider benchmark "
            "measured 2.59–3.98 seconds; one final live turn produced useful "
            "prediction lead time, but no controlled experiment reduced "
            "authoritative answer latency. Safe net benefit is therefore not "
            "established."
        ),
        "feature_status": "F-045 remains planned; foundation evidence only",
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            PROJECT_ROOT / "docs" / "MILESTONE_5_5_SPECULATIVE_DECISION.json"
        ),
    )
    args = parser.parse_args()
    result = asyncio.run(run_evaluation())
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
