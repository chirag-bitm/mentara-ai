from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass

from app.services.answer.models import AnswerProviderEvent
from app.services.answer.provider import AnswerProviderRequest


@dataclass(slots=True, frozen=True)
class FakeAnswerScript:
    """Deterministic provider steps; exceptions are raised instead of yielded."""

    steps: tuple[AnswerProviderEvent | Exception, ...]
    start_gate: asyncio.Event | None = None
    step_gates: tuple[asyncio.Event | None, ...] = ()

    def __post_init__(self) -> None:
        if self.step_gates and len(self.step_gates) != len(self.steps):
            raise ValueError("fake step gates must align with scripted steps")


class FakeAnswerProvider:
    def __init__(self, scripts: Iterable[FakeAnswerScript]) -> None:
        self._scripts = list(scripts)
        self.requests: list[AnswerProviderRequest] = []
        self.streams: list[_FakeAnswerStream] = []

    async def start(self, request: AnswerProviderRequest) -> _FakeAnswerStream:
        index = len(self.requests)
        if index >= len(self._scripts):
            raise RuntimeError("fake answer provider has no script for this request")
        script = self._scripts[index]
        self.requests.append(request)
        if script.start_gate is not None:
            await script.start_gate.wait()
        stream = _FakeAnswerStream(script)
        self.streams.append(stream)
        return stream


class _FakeAnswerStream:
    def __init__(self, script: FakeAnswerScript) -> None:
        self._script = script
        self._index = 0
        self.closed = False
        self.cancelled = False

    def __aiter__(self) -> AsyncIterator[AnswerProviderEvent]:
        return self

    async def __anext__(self) -> AnswerProviderEvent:
        if self.closed or self._index >= len(self._script.steps):
            self.closed = True
            raise StopAsyncIteration

        gate = (
            self._script.step_gates[self._index]
            if self._script.step_gates
            else None
        )
        try:
            if gate is not None:
                await gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            self.closed = True
            raise

        step = self._script.steps[self._index]
        self._index += 1
        if isinstance(step, Exception):
            self.closed = True
            raise step
        return step

    async def aclose(self) -> None:
        self.closed = True
