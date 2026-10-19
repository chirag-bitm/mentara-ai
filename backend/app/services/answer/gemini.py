from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any

import httpx
from google import genai

from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerProviderCompleted,
    AnswerProviderEvent,
    AnswerProviderTextDelta,
    AnswerUsage,
)
from app.services.answer.provider import (
    AnswerProviderError,
    AnswerProviderRequest,
)


class GeminiAnswerProvider:
    """Async, stateless Gemini Interactions adapter with no tool declarations."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        thinking_level: str,
        max_output_tokens: int = 512,
        client_factory: Callable[..., Any] = genai.Client,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key must not be empty")
        if not model.strip():
            raise ValueError("Gemini answer model must not be empty")
        if thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError("unsupported Gemini thinking level")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self._api_key = api_key
        self._model = model
        self._thinking_level = thinking_level
        self._max_output_tokens = max_output_tokens
        self._client_factory = client_factory

    async def start(self, request: AnswerProviderRequest) -> _GeminiAnswerStream:
        async_client: Any = None
        try:
            root_client = self._client_factory(
                api_key=self._api_key,
                http_options={"retry_options": {"attempts": 0}},
            )
            async_client = root_client.aio
            stream = await async_client.interactions.create(
                model=self._model,
                # Stateless Interactions requests carry an explicit local
                # history. Keep the untrusted transcript in a user_input step
                # instead of relying on the SDK's single-string shorthand.
                input=[
                    {
                        "type": "user_input",
                        "content": [
                            {
                                "type": "text",
                                "text": request.prompt.user_content,
                            }
                        ],
                    }
                ],
                system_instruction=request.prompt.system_instruction,
                generation_config={
                    "thinking_level": self._thinking_level,
                    "max_output_tokens": self._max_output_tokens,
                },
                stream=True,
                store=False,
            )
            return _GeminiAnswerStream(stream=stream, async_client=async_client)
        except BaseException as exc:
            if async_client is not None:
                with suppress(Exception):
                    await async_client.aclose()
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            raise _map_exception(exc) from None


class _GeminiAnswerStream:
    def __init__(self, *, stream: Any, async_client: Any) -> None:
        self._stream = stream
        self._iterator = stream.__aiter__()
        self._async_client = async_client
        self._sequence = 0
        self._done = False
        self._resources_closed = False

    def __aiter__(self) -> AsyncIterator[AnswerProviderEvent]:
        return self

    async def __anext__(self) -> AnswerProviderEvent:
        if self._done:
            raise StopAsyncIteration
        try:
            while True:
                event = await self._iterator.__anext__()
                event_type = getattr(event, "event_type", None)
                if event_type == "step.delta":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "type", None) != "text":
                        continue
                    text = getattr(delta, "text", None)
                    if not isinstance(text, str) or not text:
                        continue
                    self._sequence += 1
                    return AnswerProviderTextDelta(
                        sequence=self._sequence,
                        text=text,
                    )
                if event_type == "interaction.completed":
                    interaction = getattr(event, "interaction", None)
                    status = getattr(interaction, "status", None)
                    if status != "completed":
                        raise _completion_error(status)
                    self._sequence += 1
                    return AnswerProviderCompleted(
                        sequence=self._sequence,
                        usage=_usage_from_interaction(interaction),
                        finish_reason="completed",
                    )
                if event_type == "error":
                    error = getattr(event, "error", None)
                    raise _stream_error(getattr(error, "code", None))
                if event_type in {
                    "interaction.created",
                    "interaction.status_update",
                    "step.start",
                    "step.stop",
                }:
                    continue
                raise AnswerProviderError(
                    AnswerFailureCategory.MALFORMED_STREAM,
                    "Gemini returned an unsupported stream event.",
                    retryable=False,
                )
        except StopAsyncIteration:
            self._done = True
            raise
        except AnswerProviderError:
            self._done = True
            raise
        except asyncio.CancelledError:
            self._done = True
            raise
        except Exception as exc:
            self._done = True
            raise _map_exception(exc) from None

    async def aclose(self) -> None:
        if self._resources_closed:
            return
        self._resources_closed = True
        self._done = True
        close = getattr(self._stream, "close", None)
        if close is not None:
            with suppress(Exception):
                result = close()
                if hasattr(result, "__await__"):
                    await result
        with suppress(Exception):
            await self._async_client.aclose()


def _usage_from_interaction(interaction: Any) -> AnswerUsage | None:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return None
    return AnswerUsage(
        input_tokens=_nonnegative_int(getattr(usage, "total_input_tokens", None)),
        output_tokens=_nonnegative_int(getattr(usage, "total_output_tokens", None)),
        total_tokens=_nonnegative_int(getattr(usage, "total_tokens", None)),
    )


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _completion_error(status: object) -> AnswerProviderError:
    if status == "cancelled":
        return AnswerProviderError(
            AnswerFailureCategory.CANCELLATION,
            "Gemini cancelled answer generation.",
            retryable=False,
        )
    return AnswerProviderError(
        AnswerFailureCategory.PROVIDER_SERVER,
        "Gemini did not complete answer generation.",
        retryable=status in {"failed", "incomplete"},
    )


def _stream_error(code: object) -> AnswerProviderError:
    normalized = str(code or "").casefold()
    if any(token in normalized for token in ("safety", "blocked", "content")):
        return AnswerProviderError(
            AnswerFailureCategory.SAFETY_REFUSAL,
            "Gemini could not answer this content safely.",
            retryable=False,
        )
    return AnswerProviderError(
        AnswerFailureCategory.PROVIDER_SERVER,
        "Gemini answer generation failed.",
        retryable=True,
    )


def _map_exception(exc: BaseException) -> AnswerProviderError:
    if isinstance(exc, AnswerProviderError):
        return exc
    code = _provider_status_code(exc)
    error_status = _provider_error_status(exc)
    reason = _provider_reason(exc)
    if reason in {"invalid_api_key", "blocked_api_key", "legacy_standard_key"}:
        return AnswerProviderError(
            AnswerFailureCategory.AUTHENTICATION,
            "Gemini authentication failed.",
            retryable=False,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if code in {401, 403}:
        return AnswerProviderError(
            AnswerFailureCategory.AUTHENTICATION,
            "Gemini authentication failed.",
            retryable=False,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if code in {400, 404}:
        return AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            "Gemini answer configuration is invalid.",
            retryable=False,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if code == 429:
        return AnswerProviderError(
            AnswerFailureCategory.RATE_LIMIT,
            "Gemini answer quota is temporarily unavailable.",
            retryable=True,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or code in {408, 504}:
        return AnswerProviderError(
            AnswerFailureCategory.TIMEOUT,
            "Gemini answer generation timed out.",
            retryable=True,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if isinstance(exc, (OSError, httpx.TransportError)):
        return AnswerProviderError(
            AnswerFailureCategory.TRANSIENT_NETWORK,
            "Gemini answer connection failed temporarily.",
            retryable=True,
        )
    if isinstance(code, int) and code >= 500:
        return AnswerProviderError(
            AnswerFailureCategory.PROVIDER_SERVER,
            "Gemini answer service is temporarily unavailable.",
            retryable=True,
            provider_status_code=code,
            provider_error_status=error_status,
            provider_reason=reason,
        )
    if isinstance(exc, (TypeError, ValueError)):
        return AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            "Gemini answer configuration is invalid.",
            retryable=False,
        )
    return AnswerProviderError(
        AnswerFailureCategory.UNKNOWN,
        "Gemini answer generation failed.",
        retryable=False,
    )


def _provider_status_code(exc: BaseException) -> int | None:
    """Read status codes from both legacy and Interactions SDK errors."""

    for candidate in (
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if isinstance(candidate, int) and 100 <= candidate <= 599:
            return candidate
    return None


def _provider_error_body(exc: BaseException) -> dict[str, Any]:
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (TypeError, ValueError):
            body = {"message": body}
    model_dump = getattr(body, "model_dump", None)
    if callable(model_dump):
        with suppress(Exception):
            body = model_dump(mode="python")
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    return error if isinstance(error, dict) else body


def _provider_error_status(exc: BaseException) -> str | None:
    status = _provider_error_body(exc).get("status")
    if not isinstance(status, str):
        return None
    normalized = status.strip().upper()
    if not normalized or len(normalized) > 64:
        return None
    return (
        normalized
        if all(char.isalnum() or char == "_" for char in normalized)
        else None
    )


def _provider_reason(exc: BaseException) -> str | None:
    """Classify a raw provider message into a small safe allow-list."""

    body = _provider_error_body(exc)
    message = body.get("message")
    if not isinstance(message, str):
        message = getattr(exc, "message", None)
    normalized = message.casefold() if isinstance(message, str) else ""
    patterns = (
        (("api key", "not valid"), "invalid_api_key"),
        (("api key", "invalid"), "invalid_api_key"),
        (("api key", "leaked"), "blocked_api_key"),
        (("api key", "blocked"), "blocked_api_key"),
        (("api key", "expired"), "invalid_api_key"),
        (("standard", "key", "rejected"), "legacy_standard_key"),
        (("unrestricted", "key"), "legacy_standard_key"),
        (("location", "not supported"), "unsupported_location"),
        (("billing",), "billing_required"),
        (("model", "not found"), "model_unavailable"),
        (("model", "not supported"), "model_unavailable"),
        (("thinking_level",), "thinking_level_invalid"),
        (("thinking level",), "thinking_level_invalid"),
        (("max_output_tokens",), "generation_config_invalid"),
        (("generation_config",), "generation_config_invalid"),
        (("generation config",), "generation_config_invalid"),
        (("system_instruction",), "system_instruction_invalid"),
        (("system instruction",), "system_instruction_invalid"),
        (("store",), "store_option_invalid"),
    )
    for needles, reason in patterns:
        if all(needle in normalized for needle in needles):
            return reason

    details = body.get("details")
    if isinstance(details, list):
        for detail in details:
            if not isinstance(detail, dict):
                continue
            raw_reason = detail.get("reason")
            if isinstance(raw_reason, str):
                safe_reason = raw_reason.strip().lower()
                if safe_reason and all(
                    char.isalnum() or char == "_" for char in safe_reason
                ):
                    return safe_reason[:64]
    return "invalid_request" if _provider_status_code(exc) == 400 else None
