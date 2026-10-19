from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

from app.services.prediction.provider import (
    PredictionProviderRequest,
    PredictionProviderResult,
)


@dataclass(slots=True, frozen=True)
class FakePredictionScript:
    """One deterministic result or failure with an optional race gate."""

    result: PredictionProviderResult | None = None
    error: BaseException | None = None
    gate: asyncio.Event | None = None
    suppress_cancellation: bool = False

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("fake prediction script needs exactly one outcome")


class FakePredictionProvider:
    def __init__(self, scripts: Iterable[FakePredictionScript]) -> None:
        self._scripts = list(scripts)
        self.requests: list[PredictionProviderRequest] = []
        self.cancelled_call_count = 0
        self.active_call_count = 0
        self.max_active_call_count = 0

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult:
        index = len(self.requests)
        if index >= len(self._scripts):
            raise RuntimeError("fake prediction provider has no script for this request")
        script = self._scripts[index]
        self.requests.append(request)
        self.active_call_count += 1
        self.max_active_call_count = max(
            self.max_active_call_count,
            self.active_call_count,
        )
        try:
            if script.gate is not None:
                try:
                    await script.gate.wait()
                except asyncio.CancelledError:
                    self.cancelled_call_count += 1
                    if not script.suppress_cancellation:
                        raise
            if script.error is not None:
                raise script.error
            if script.result is None:
                raise AssertionError("fake prediction script has no result")
            return script.result
        finally:
            self.active_call_count -= 1
