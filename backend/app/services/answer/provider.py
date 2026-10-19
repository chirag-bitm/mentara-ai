from __future__ import annotations

import re
from dataclasses import dataclass
from typing import AsyncIterator, Protocol
from uuid import UUID

from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerPrompt,
    AnswerProviderEvent,
)


@dataclass(slots=True, frozen=True)
class AnswerProviderRequest:
    answer_id: UUID
    attempt: int
    prompt: AnswerPrompt

    def __post_init__(self) -> None:
        if self.attempt < 1:
            raise ValueError("provider request attempt must be positive")


class AnswerProviderStream(Protocol):
    def __aiter__(self) -> AsyncIterator[AnswerProviderEvent]: ...

    async def aclose(self) -> None: ...


class AnswerProvider(Protocol):
    """Provider-neutral streaming boundary implemented by real/fake adapters."""

    async def start(self, request: AnswerProviderRequest) -> AnswerProviderStream: ...


class AnswerProviderError(Exception):
    def __init__(
        self,
        category: AnswerFailureCategory,
        safe_message: str,
        *,
        retryable: bool,
        provider_status_code: int | None = None,
        provider_error_status: str | None = None,
        provider_reason: str | None = None,
    ) -> None:
        if not safe_message.strip():
            raise ValueError("safe provider error message must not be empty")
        if (
            provider_status_code is not None
            and not 100 <= provider_status_code <= 599
        ):
            raise ValueError("provider status code must be a valid HTTP status")
        for value, label in (
            (provider_error_status, "provider error status"),
            (provider_reason, "provider reason"),
        ):
            if (
                value is not None
                and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", value)
                is None
            ):
                raise ValueError(f"{label} must be a safe identifier")
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.retryable = retryable
        # Safe diagnostic metadata for backend tooling only. Browser answer
        # events intentionally expose the provider-neutral category/message.
        self.provider_status_code = provider_status_code
        self.provider_error_status = provider_error_status
        self.provider_reason = provider_reason
