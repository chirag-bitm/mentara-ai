import asyncio
from uuid import UUID

import pytest

from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerPrompt,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
    AnswerUsage,
)
from app.services.answer.provider import AnswerProviderError, AnswerProviderRequest


def _request() -> AnswerProviderRequest:
    return AnswerProviderRequest(
        answer_id=UUID("20000000-0000-0000-0000-000000000001"),
        attempt=1,
        prompt=AnswerPrompt(system_instruction="policy", user_content="user text"),
    )


def test_fake_provider_streams_ordered_deltas_and_completion() -> None:
    async def scenario() -> None:
        usage = AnswerUsage(input_tokens=5, output_tokens=2, total_tokens=7)
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="hello "),
                        AnswerProviderTextDelta(sequence=2, text="world"),
                        AnswerProviderCompleted(sequence=3, usage=usage),
                    )
                )
            ]
        )
        stream = await provider.start(_request())
        events = [event async for event in stream]

        assert [event.sequence for event in events] == [1, 2, 3]
        assert provider.requests == [_request()]
        assert stream.closed
        assert events[-1] == AnswerProviderCompleted(sequence=3, usage=usage)

    asyncio.run(scenario())


def test_fake_provider_can_fail_before_or_after_text() -> None:
    async def scenario() -> None:
        failure = AnswerProviderError(
            AnswerFailureCategory.RATE_LIMIT,
            "Answer provider is temporarily rate limited.",
            retryable=True,
        )
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(steps=(failure,)),
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="partial"),
                        failure,
                    )
                ),
            ]
        )

        before = await provider.start(_request())
        with pytest.raises(AnswerProviderError) as caught:
            await before.__anext__()
        assert caught.value.category is AnswerFailureCategory.RATE_LIMIT

        after = await provider.start(_request())
        assert await after.__anext__() == AnswerProviderTextDelta(
            sequence=1,
            text="partial",
        )
        with pytest.raises(AnswerProviderError):
            await after.__anext__()

    asyncio.run(scenario())


def test_fake_provider_gate_supports_deterministic_cancellation() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderTextDelta(sequence=1, text="late"),),
                    step_gates=(gate,),
                )
            ]
        )
        stream = await provider.start(_request())
        pending = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

        assert stream.cancelled
        assert stream.closed

    asyncio.run(scenario())
