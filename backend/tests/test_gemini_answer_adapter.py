import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.answer.gemini import GeminiAnswerProvider
from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerPrompt,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
)
from app.services.answer.provider import AnswerProviderError, AnswerProviderRequest


class FakeRawStream:
    def __init__(self, events) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class FakeInteractions:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeAsyncClient:
    def __init__(self, result) -> None:
        self.interactions = FakeInteractions(result)
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeRootClient:
    def __init__(self, result) -> None:
        self.aio = FakeAsyncClient(result)


class FakeSDKError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__("raw provider detail must be sanitized")
        self.code = code


class FakeInteractionsSDKError(Exception):
    def __init__(self, status_code: int, *, body=None) -> None:
        super().__init__("raw Interactions detail must be sanitized")
        self.status_code = status_code
        self.body = body


def _request() -> AnswerProviderRequest:
    return AnswerProviderRequest(
        answer_id=UUID("20000000-0000-0000-0000-000000000001"),
        attempt=1,
        prompt=AnswerPrompt(
            system_instruction="trusted system policy",
            user_content="untrusted transcript content",
        ),
    )


def _provider(result, roots: list[FakeRootClient]) -> GeminiAnswerProvider:
    def factory(*, api_key: str, http_options):
        assert api_key == "secret-key"
        assert http_options == {"retry_options": {"attempts": 0}}
        root = FakeRootClient(result)
        roots.append(root)
        return root

    return GeminiAnswerProvider(
        api_key="secret-key",
        model="gemini-3.5-flash-lite",
        thinking_level="minimal",
        client_factory=factory,
    )


def test_interactions_stream_is_async_stateless_and_provider_neutral() -> None:
    async def scenario() -> None:
        raw = FakeRawStream(
            [
                SimpleNamespace(event_type="interaction.created"),
                SimpleNamespace(
                    event_type="step.delta",
                    delta=SimpleNamespace(type="thought_signature", signature="hidden"),
                ),
                SimpleNamespace(
                    event_type="step.delta",
                    delta=SimpleNamespace(type="text", text="Hello "),
                ),
                SimpleNamespace(
                    event_type="step.delta",
                    delta=SimpleNamespace(type="text", text="world"),
                ),
                SimpleNamespace(
                    event_type="interaction.completed",
                    interaction=SimpleNamespace(
                        status="completed",
                        usage=SimpleNamespace(
                            total_input_tokens=10,
                            total_output_tokens=2,
                            total_tokens=15,
                        ),
                    ),
                ),
            ]
        )
        roots: list[FakeRootClient] = []
        stream = await _provider(raw, roots).start(_request())
        events = [event async for event in stream]
        await stream.aclose()

        assert events[:2] == [
            AnswerProviderTextDelta(sequence=1, text="Hello "),
            AnswerProviderTextDelta(sequence=2, text="world"),
        ]
        assert isinstance(events[2], AnswerProviderCompleted)
        assert events[2].sequence == 3
        assert events[2].usage is not None
        assert events[2].usage.total_tokens == 15

        call = roots[0].aio.interactions.calls[0]
        assert call["model"] == "gemini-3.5-flash-lite"
        assert call["input"] == [
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": "untrusted transcript content",
                    }
                ],
            }
        ]
        assert call["system_instruction"] == "trusted system policy"
        assert call["generation_config"] == {
            "thinking_level": "minimal",
            "max_output_tokens": 512,
        }
        assert call["stream"] is True
        assert call["store"] is False
        assert "previous_interaction_id" not in call
        assert "tools" not in call
        assert raw.closed
        assert roots[0].aio.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("code", "category", "retryable"),
    (
        (401, AnswerFailureCategory.AUTHENTICATION, False),
        (404, AnswerFailureCategory.CONFIGURATION, False),
        (429, AnswerFailureCategory.RATE_LIMIT, True),
        (503, AnswerFailureCategory.PROVIDER_SERVER, True),
    ),
)
def test_sdk_start_errors_are_sanitized(code, category, retryable) -> None:
    async def scenario() -> None:
        roots: list[FakeRootClient] = []
        with pytest.raises(AnswerProviderError) as caught:
            await _provider(FakeSDKError(code), roots).start(_request())
        assert caught.value.category is category
        assert caught.value.retryable is retryable
        assert caught.value.provider_status_code == code
        assert "raw provider detail" not in caught.value.safe_message
        assert roots[0].aio.closed

    asyncio.run(scenario())


def test_interactions_sdk_status_code_is_classified_and_sanitized() -> None:
    async def scenario() -> None:
        roots: list[FakeRootClient] = []
        with pytest.raises(AnswerProviderError) as caught:
            await _provider(
                FakeInteractionsSDKError(
                    404,
                    body={
                        "error": {
                            "status": "NOT_FOUND",
                            "message": "The requested model was not found.",
                        }
                    },
                ),
                roots,
            ).start(_request())

        assert caught.value.category is AnswerFailureCategory.CONFIGURATION
        assert caught.value.provider_status_code == 404
        assert caught.value.provider_error_status == "NOT_FOUND"
        assert caught.value.provider_reason == "model_unavailable"
        assert "raw Interactions detail" not in caught.value.safe_message
        assert roots[0].aio.closed

    asyncio.run(scenario())


def test_interactions_invalid_key_at_http_400_maps_to_authentication() -> None:
    async def scenario() -> None:
        roots: list[FakeRootClient] = []
        error = FakeInteractionsSDKError(
            400,
            body={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "API key not valid. Please pass a valid API key.",
                }
            },
        )
        with pytest.raises(AnswerProviderError) as caught:
            await _provider(error, roots).start(_request())

        assert caught.value.category is AnswerFailureCategory.AUTHENTICATION
        assert caught.value.provider_status_code == 400
        assert caught.value.provider_error_status == "INVALID_ARGUMENT"
        assert caught.value.provider_reason == "invalid_api_key"
        assert "API key" not in caught.value.safe_message

    asyncio.run(scenario())


def test_interactions_json_string_body_is_safely_classified() -> None:
    async def scenario() -> None:
        roots: list[FakeRootClient] = []
        error = FakeInteractionsSDKError(
            400,
            body=(
                '{"error":{"status":"INVALID_ARGUMENT",'
                '"message":"API key expired. Create a replacement."}}'
            ),
        )
        with pytest.raises(AnswerProviderError) as caught:
            await _provider(error, roots).start(_request())

        assert caught.value.category is AnswerFailureCategory.AUTHENTICATION
        assert caught.value.provider_error_status == "INVALID_ARGUMENT"
        assert caught.value.provider_reason == "invalid_api_key"
        assert "expired" not in caught.value.safe_message

    asyncio.run(scenario())


def test_local_sdk_validation_failure_is_configuration_error() -> None:
    async def scenario() -> None:
        roots: list[FakeRootClient] = []
        with pytest.raises(AnswerProviderError) as caught:
            await _provider(TypeError("raw local validation detail"), roots).start(
                _request()
            )

        assert caught.value.category is AnswerFailureCategory.CONFIGURATION
        assert caught.value.provider_status_code is None
        assert "raw local validation detail" not in caught.value.safe_message

    asyncio.run(scenario())


def test_safety_error_and_unknown_event_are_sanitized() -> None:
    async def scenario() -> None:
        safety_raw = FakeRawStream(
            [
                SimpleNamespace(
                    event_type="error",
                    error=SimpleNamespace(code="CONTENT_SAFETY_BLOCKED"),
                )
            ]
        )
        roots: list[FakeRootClient] = []
        safety = await _provider(safety_raw, roots).start(_request())
        with pytest.raises(AnswerProviderError) as caught:
            await safety.__anext__()
        assert caught.value.category is AnswerFailureCategory.SAFETY_REFUSAL
        await safety.aclose()
        assert safety_raw.closed

        unknown_raw = FakeRawStream([SimpleNamespace(event_type="new.event")])
        malformed = await _provider(unknown_raw, roots).start(_request())
        with pytest.raises(AnswerProviderError) as caught:
            await malformed.__anext__()
        assert caught.value.category is AnswerFailureCategory.MALFORMED_STREAM
        await malformed.aclose()
        assert unknown_raw.closed

    asyncio.run(scenario())
