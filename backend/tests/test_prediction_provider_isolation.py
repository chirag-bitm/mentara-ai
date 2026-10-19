import asyncio
import threading
import time
from uuid import UUID

import pytest

from app.services.prediction.models import PredictionPrompt
from app.services.prediction.provider import (
    EventLoopIsolatedPredictionProvider,
    PredictionProviderRequest,
    PredictionProviderResult,
)


def _request() -> PredictionProviderRequest:
    return PredictionProviderRequest(
        prediction_id=UUID("00000000-0000-0000-0000-000000000123"),
        input_revision=1,
        attempt=1,
        prompt=PredictionPrompt(
            system_instruction="Return bounded advisory candidates.",
            user_content="Untrusted bounded demo context.",
        ),
        max_candidates=1,
        max_output_tokens=64,
    )


class _BlockingProvider:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.thread_name: str | None = None

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult:
        del request
        self.thread_name = threading.current_thread().name
        time.sleep(self.delay_seconds)
        return PredictionProviderResult(candidates=())


class _CancellableProvider:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancelled = threading.Event()

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult:
        del request
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def test_blocking_provider_work_cannot_starve_realtime_event_loop() -> None:
    async def scenario() -> None:
        inner = _BlockingProvider(delay_seconds=0.25)
        provider = EventLoopIsolatedPredictionProvider(inner)
        prediction = asyncio.create_task(provider.predict(_request()))

        started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.02)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.15
        assert await prediction == PredictionProviderResult(candidates=())
        assert inner.thread_name == "mentara-prediction-provider"

    asyncio.run(scenario())


def test_outer_cancellation_reaches_isolated_provider_without_leaked_worker() -> None:
    async def scenario() -> None:
        inner = _CancellableProvider()
        provider = EventLoopIsolatedPredictionProvider(inner)
        prediction = asyncio.create_task(provider.predict(_request()))

        assert await asyncio.to_thread(inner.started.wait, 1.0)
        prediction.cancel()
        with pytest.raises(asyncio.CancelledError):
            await prediction
        assert await asyncio.to_thread(inner.cancelled.wait, 1.0)

        await asyncio.sleep(0)
        assert not any(
            thread.name == "mentara-prediction-provider"
            for thread in threading.enumerate()
        )

    asyncio.run(scenario())


def test_wrapped_provider_failure_is_preserved() -> None:
    class FailingProvider:
        async def predict(
            self,
            request: PredictionProviderRequest,
        ) -> PredictionProviderResult:
            del request
            raise RuntimeError("local-test-failure")

    async def scenario() -> None:
        provider = EventLoopIsolatedPredictionProvider(FailingProvider())
        with pytest.raises(RuntimeError, match="local-test-failure"):
            await provider.predict(_request())

    asyncio.run(scenario())
