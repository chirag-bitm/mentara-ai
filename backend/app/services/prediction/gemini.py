from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Literal

import httpx
from google import genai
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.prediction.models import (
    MAX_PREDICTION_ANCHOR_TERM_CHARS,
    MAX_PREDICTION_ANCHOR_TERMS,
    MAX_PREDICTION_CANDIDATE_CHARS,
    MAX_PREDICTION_CANDIDATES,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionUsage,
)
from app.services.prediction.provider import (
    PredictionProviderError,
    PredictionProviderRequest,
    PredictionProviderResult,
)


class _GeminiCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["question", "request", "topic"]
    text: str = Field(min_length=1, max_length=MAX_PREDICTION_CANDIDATE_CHARS)
    anchor_terms: list[str] = Field(
        default_factory=list,
        max_length=MAX_PREDICTION_ANCHOR_TERMS,
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("candidate text must be trimmed")
        return value

    @field_validator("anchor_terms")
    @classmethod
    def validate_anchor_terms(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("anchor terms must be unique")
        if any(
            not value
            or value != value.strip()
            or len(value) > MAX_PREDICTION_ANCHOR_TERM_CHARS
            for value in values
        ):
            raise ValueError("anchor terms must be trimmed and bounded")
        return values


class _GeminiPredictionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_GeminiCandidate] = Field(max_length=MAX_PREDICTION_CANDIDATES)


class GeminiPredictionProvider:
    """One-shot stateless Gemini Interactions adapter with no tools."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        thinking_level: str,
        client_factory: Callable[..., Any] = genai.Client,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key must not be empty")
        if not model.strip():
            raise ValueError("Gemini prediction model must not be empty")
        if thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError("unsupported Gemini thinking level")
        self._api_key = api_key
        self._model = model
        self._thinking_level = thinking_level
        self._client_factory = client_factory

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult:
        async_client: Any = None
        try:
            response_schema = _GeminiPredictionOutput.model_json_schema()
            response_schema["properties"]["candidates"]["maxItems"] = (
                request.max_candidates
            )
            root_client = self._client_factory(
                api_key=self._api_key,
                http_options={"retry_options": {"attempts": 0}},
            )
            async_client = root_client.aio
            interaction = await async_client.interactions.create(
                model=self._model,
                input=[
                    {
                        "type": "user_input",
                        "content": [
                            {"type": "text", "text": request.prompt.user_content}
                        ],
                    }
                ],
                system_instruction=request.prompt.system_instruction,
                generation_config={
                    "thinking_level": self._thinking_level,
                    "max_output_tokens": request.max_output_tokens,
                },
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": response_schema,
                },
                stream=False,
                store=False,
            )
            if getattr(interaction, "status", None) != "completed":
                raise _completion_error(getattr(interaction, "status", None))
            output_text = getattr(interaction, "output_text", None)
            if not isinstance(output_text, str) or not output_text.strip():
                raise PredictionProviderError(
                    PredictionFailureCategory.MALFORMED_OUTPUT,
                    "Gemini returned invalid prediction output.",
                    retryable=False,
                )
            parsed = _GeminiPredictionOutput.model_validate_json(output_text)
            if len(parsed.candidates) > request.max_candidates:
                raise PredictionProviderError(
                    PredictionFailureCategory.MALFORMED_OUTPUT,
                    "Gemini exceeded the prediction candidate limit.",
                    retryable=False,
                )
            try:
                candidates = tuple(
                    PredictionCandidate(
                        kind=PredictionCandidateKind(candidate.kind),
                        text=candidate.text,
                        anchor_terms=tuple(candidate.anchor_terms),
                    )
                    for candidate in parsed.candidates
                )
                return PredictionProviderResult(
                    candidates=candidates,
                    usage=_usage_from_interaction(interaction),
                    finish_reason="completed",
                )
            except ValueError:
                raise PredictionProviderError(
                    PredictionFailureCategory.MALFORMED_OUTPUT,
                    "Gemini returned invalid prediction output.",
                    retryable=False,
                ) from None
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                raise
            if isinstance(exc, PredictionProviderError):
                raise
            if isinstance(exc, (ValidationError, json.JSONDecodeError)):
                raise PredictionProviderError(
                    PredictionFailureCategory.MALFORMED_OUTPUT,
                    "Gemini returned invalid prediction output.",
                    retryable=False,
                ) from None
            raise _map_exception(exc) from None
        finally:
            if async_client is not None:
                with suppress(Exception):
                    await async_client.aclose()


def _usage_from_interaction(interaction: Any) -> PredictionUsage | None:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return None
    return PredictionUsage(
        input_tokens=_nonnegative_int(getattr(usage, "total_input_tokens", None)),
        output_tokens=_nonnegative_int(getattr(usage, "total_output_tokens", None)),
        total_tokens=_nonnegative_int(getattr(usage, "total_tokens", None)),
    )


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _completion_error(status: object) -> PredictionProviderError:
    # Expose only a fixed SDK status label. Interaction errors and steps may
    # contain conversation text and must never be copied into diagnostics.
    known_statuses = {
        "in_progress",
        "requires_action",
        "completed",
        "failed",
        "cancelled",
        "incomplete",
        "budget_exceeded",
        "queued",
    }
    reason = (
        f"interaction_{status}"
        if isinstance(status, str) and status in known_statuses
        else "interaction_unknown_status"
    )
    if status == "cancelled":
        return PredictionProviderError(
            PredictionFailureCategory.CANCELLATION,
            "Gemini cancelled prediction.",
            retryable=False,
            provider_reason=reason,
        )
    return PredictionProviderError(
        PredictionFailureCategory.PROVIDER_SERVER,
        "Gemini did not complete prediction.",
        retryable=status == "failed",
        provider_reason=reason,
    )


def _map_exception(exc: BaseException) -> PredictionProviderError:
    code = _provider_status_code(exc)
    error_status = _provider_error_status(exc)
    reason = _provider_reason(exc)
    common = {
        "provider_status_code": code,
        "provider_error_status": error_status,
        "provider_reason": reason,
    }
    if reason in {"invalid_api_key", "blocked_api_key", "legacy_standard_key"}:
        return PredictionProviderError(
            PredictionFailureCategory.AUTHENTICATION,
            "Gemini prediction authentication failed.",
            retryable=False,
            **common,
        )
    if code in {401, 403}:
        return PredictionProviderError(
            PredictionFailureCategory.AUTHENTICATION,
            "Gemini prediction authentication failed.",
            retryable=False,
            **common,
        )
    if code in {400, 404}:
        return PredictionProviderError(
            PredictionFailureCategory.CONFIGURATION,
            "Gemini prediction configuration is invalid.",
            retryable=False,
            **common,
        )
    if code == 429:
        return PredictionProviderError(
            PredictionFailureCategory.RATE_LIMIT,
            "Gemini prediction quota is temporarily unavailable.",
            retryable=True,
            **common,
        )
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or code in {408, 504}:
        return PredictionProviderError(
            PredictionFailureCategory.TIMEOUT,
            "Gemini prediction timed out.",
            retryable=True,
            **common,
        )
    if isinstance(exc, (OSError, httpx.TransportError)):
        return PredictionProviderError(
            PredictionFailureCategory.TRANSIENT_NETWORK,
            "Gemini prediction connection failed temporarily.",
            retryable=True,
        )
    if isinstance(code, int) and code >= 500:
        return PredictionProviderError(
            PredictionFailureCategory.PROVIDER_SERVER,
            "Gemini prediction service is temporarily unavailable.",
            retryable=True,
            **common,
        )
    if isinstance(exc, (TypeError, ValueError)):
        return PredictionProviderError(
            PredictionFailureCategory.CONFIGURATION,
            "Gemini prediction configuration is invalid.",
            retryable=False,
        )
    return PredictionProviderError(
        PredictionFailureCategory.UNKNOWN,
        "Gemini prediction failed.",
        retryable=False,
    )


def _provider_status_code(exc: BaseException) -> int | None:
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
        (("model", "not found"), "model_unavailable"),
        (("model", "not supported"), "model_unavailable"),
        (("thinking_level",), "thinking_level_invalid"),
        (("thinking level",), "thinking_level_invalid"),
        (("response_format",), "response_format_invalid"),
        (("response format",), "response_format_invalid"),
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
    return "invalid_request" if code_is_bad_request(exc) else None


def code_is_bad_request(exc: BaseException) -> bool:
    return _provider_status_code(exc) == 400
