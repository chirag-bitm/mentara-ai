from __future__ import annotations

import pytest

from app.services.prediction import (
    ConservativeAppendOnlyPredictionCompatibilityPolicy,
    PredictionInputCompatibilityLimits,
    PredictionRuntimeLimits,
)


def _policy(limit: int = 96) -> ConservativeAppendOnlyPredictionCompatibilityPolicy:
    return ConservativeAppendOnlyPredictionCompatibilityPolicy(
        limits=PredictionInputCompatibilityLimits(max_extension_chars=limit)
    )


@pytest.mark.parametrize(
    "current",
    [
        "You mentioned Redis in",
        "You mentioned Redis in your",
        "You mentioned Redis in your architecture",
        "You mentioned Redis in your architecture and",
        (
            "You mentioned Redis in your architecture "
            "and I am interested in the tradeoffs"
        ),
        "You mentioned Redis in your architecture and",
        "You mentioned Redis in your architecture and I am interested",
        (
            "You mentioned Redis in your architecture "
            "and I am interested in the tradeoffs"
        ),
        "You mentioned Redis in your architecture particularly",
    ],
)
def test_short_neutral_append_only_prefaces_are_compatible(current: str) -> None:
    basis = (
        "You mentioned Redis"
        if current.startswith("You mentioned Redis in")
        else "You mentioned Redis in your architecture"
    )
    assert _policy().allows_extension(
        basis,
        current,
    )


@pytest.mark.parametrize(
    ("basis", "current"),
    [
        (
            "You mentioned Redis in your architecture and I am interested in the",
            (
                "You mentioned Redis in your architecture and I am interested "
                "in the trade-offs"
            ),
        ),
        (
            "You mentioned Redis in your architecture and I am interested",
            (
                "You mentioned Redis in your architecture and I am interested "
                "in the tradeoffs"
            ),
        ),
        (
            "You mentioned Redis in your architecture and I am interested in trade",
            (
                "You mentioned Redis in your architecture and I am interested "
                "in trade-offs"
            ),
        ),
        (
            "You mentioned Redis in your architecture, and I am interested",
            "You mentioned Redis in your architecture and I am interested",
        ),
        (
            "YOU MENTIONED REDIS IN YOUR ARCHITECTURE AND I AM INTERESTED",
            "You mentioned Redis in your architecture and I am interested",
        ),
        (
            "You mention Redis in your architecture",
            (
                "You mentioned Redis in your architecture and I am interested "
                "in the tradeoffs"
            ),
        ),
        (
            "You mentioned Redis in your architecture and I am interested",
            (
                "You mentioned Redis in your architecture and I am interested "
                "in the trade-offs."
            ),
        ),
    ],
)
def test_real_stt_neutral_completion_and_cosmetic_rewrites_are_compatible(
    basis: str,
    current: str,
) -> None:
    """Keep one paid attempt across bounded, meaning-preserving STT churn."""

    assert _policy().allows_extension(basis, current)


@pytest.mark.parametrize(
    ("basis", "current"),
    [
        (
            "You mentioned Redis in your architecture",
            "You mentioned cache behavior in your architecture",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture, actually DynamoDB",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture and I am interested, actually, no",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture but Kafka is the concern",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture and what happens if it fails",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture and wh",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture and I am interested ky",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture and I am not interested",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture. Now the deployment",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture...",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture?",
        ),
        (
            "You mentioned Redis in your architecture",
            "You mentioned Redis in your architecture regarding kafka",
        ),
        (
            "You mentioned Redis in your architecture and I am interested in trade",
            "You mentioned Redis in your architecture and I am interested in DynamoDB",
        ),
        (
            "You mentioned Redis in your architecture and I am interested",
            "You mentioned Redis architecture and I am interested",
        ),
        (
            "You mentioned Redis in your architecture",
            "You discussed Redis in your architecture and I am interested",
        ),
        (
            "You mentioned Redis in your architecture and I am interested",
            "You mentioned Redis and I am interested in your architecture",
        ),
    ],
)
def test_corrections_intent_boundaries_and_new_topics_fail_closed(
    basis: str,
    current: str,
) -> None:
    assert not _policy().allows_extension(basis, current)


def test_compatibility_is_bounded_and_can_be_disabled() -> None:
    basis = "You mentioned Redis in your architecture"
    current = f"{basis} and I am interested in " + ("details " * 20)

    assert not _policy(limit=48).allows_extension(basis, current)
    assert not _policy(limit=48).allows_extension(basis, basis + ("," * 100))
    assert not _policy(limit=0).allows_extension(
        basis,
        f"{basis} and I am interested",
    )


def test_direct_question_basis_never_uses_extension_compatibility() -> None:
    assert not _policy().allows_extension(
        "Why did you choose Redis",
        "Why did you choose Redis particularly for this system",
    )


@pytest.mark.parametrize("limit", [-1, 513])
def test_runtime_rejects_unbounded_compatible_extension_limits(limit: int) -> None:
    with pytest.raises(ValueError, match="compatible extension limit"):
        PredictionRuntimeLimits(
            coalesce_seconds=0,
            provider_timeout_seconds=1,
            max_attempts_per_turn=1,
            max_calls_per_session=1,
            max_compatible_extension_chars=limit,
        )
