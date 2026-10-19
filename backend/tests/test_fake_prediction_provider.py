import asyncio
from uuid import UUID

import pytest

from app.services.prediction import (
    FakePredictionProvider,
    FakePredictionScript,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionPrompt,
    PredictionProviderError,
    PredictionProviderRequest,
    PredictionProviderResult,
    PredictionUsage,
)


def _request(attempt: int = 1) -> PredictionProviderRequest:
    return PredictionProviderRequest(
        prediction_id=UUID("33000000-0000-0000-0000-000000000001"),
        input_revision=attempt,
        attempt=attempt,
        prompt=PredictionPrompt(
            system_instruction="trusted policy",
            user_content="untrusted conversation",
        ),
        max_candidates=3,
        max_output_tokens=128,
    )


def _result(text: str = "Why did you choose Redis?") -> PredictionProviderResult:
    return PredictionProviderResult(
        candidates=(
            PredictionCandidate(
                kind=PredictionCandidateKind.QUESTION,
                text=text,
                anchor_terms=("redis",),
            ),
        ),
        usage=PredictionUsage(input_tokens=30, output_tokens=8, total_tokens=38),
        finish_reason="stop",
    )


def test_fake_provider_returns_scripted_results_in_request_order() -> None:
    async def scenario() -> None:
        provider = FakePredictionProvider(
            [
                FakePredictionScript(result=_result()),
                FakePredictionScript(result=_result("What if Redis fails?")),
            ]
        )

        assert await provider.predict(_request(1)) == _result()
        assert await provider.predict(_request(2)) == _result("What if Redis fails?")
        assert provider.requests == [_request(1), _request(2)]
        assert provider.active_call_count == 0
        assert provider.max_active_call_count == 1

    asyncio.run(scenario())


def test_fake_provider_supports_failure_and_deterministic_cancellation() -> None:
    async def scenario() -> None:
        failure = PredictionProviderError(
            PredictionFailureCategory.TRANSIENT_NETWORK,
            "Prediction connection failed temporarily.",
            retryable=True,
        )
        gate = asyncio.Event()
        provider = FakePredictionProvider(
            [
                FakePredictionScript(error=failure),
                FakePredictionScript(result=_result(), gate=gate),
            ]
        )

        with pytest.raises(PredictionProviderError) as caught:
            await provider.predict(_request())
        assert caught.value.category is PredictionFailureCategory.TRANSIENT_NETWORK

        pending = asyncio.create_task(provider.predict(_request(2)))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert provider.cancelled_call_count == 1
        assert provider.active_call_count == 0

    asyncio.run(scenario())


def test_fake_provider_can_model_a_late_completion_after_cancellation() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakePredictionProvider(
            [
                FakePredictionScript(
                    result=_result(),
                    gate=gate,
                    suppress_cancellation=True,
                )
            ]
        )
        pending = asyncio.create_task(provider.predict(_request()))
        await asyncio.sleep(0)
        pending.cancel()

        assert await pending == _result()
        assert provider.cancelled_call_count == 1
        assert provider.active_call_count == 0

    asyncio.run(scenario())


def test_fake_script_and_exhaustion_fail_closed() -> None:
    with pytest.raises(ValueError, match="exactly one outcome"):
        FakePredictionScript()
    with pytest.raises(ValueError, match="exactly one outcome"):
        FakePredictionScript(result=_result(), error=RuntimeError("both"))

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="no script"):
            await FakePredictionProvider([]).predict(_request())

    asyncio.run(scenario())
