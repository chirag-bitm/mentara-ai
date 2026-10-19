from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from typing import Protocol
from uuid import UUID

from app.schemas.events import (
    AnswerCancelledEvent,
    AnswerCompletedEvent,
    AnswerDeltaEvent,
    AnswerFailedEvent,
    AnswerSupersededEvent,
    PredictionSnapshotEvent,
)


class SerializableEvent(Protocol):
    def model_dump(self, *, mode: str, exclude_none: bool) -> dict[str, object]: ...


class JsonWebSocket(Protocol):
    async def send_json(self, data: object) -> None: ...


class OutboundBufferFull(RuntimeError):
    pass


_ANSWER_TERMINAL_TYPES = (
    AnswerCompletedEvent,
    AnswerCancelledEvent,
    AnswerSupersededEvent,
    AnswerFailedEvent,
)


class OutboundEventBuffer:
    """Bounded priority buffer with one coalesced delta per active answer."""

    def __init__(self, *, max_items: int, max_coalesced_delta_chars: int) -> None:
        if max_items < 2:
            raise ValueError("outbound buffer must hold at least two events")
        if max_coalesced_delta_chars < 1:
            raise ValueError("coalesced delta limit must be positive")
        self._max_items = max_items
        self._max_coalesced_delta_chars = max_coalesced_delta_chars
        self._important: deque[SerializableEvent] = deque()
        self._deltas: OrderedDict[UUID, AnswerDeltaEvent] = OrderedDict()
        self._predictions: OrderedDict[UUID, PredictionSnapshotEvent] = OrderedDict()

    def __len__(self) -> int:
        return len(self._important) + len(self._deltas) + len(self._predictions)

    def put(self, event: SerializableEvent) -> None:
        if isinstance(event, AnswerDeltaEvent):
            self._put_delta(event)
            return
        if isinstance(event, PredictionSnapshotEvent):
            self._put_prediction(event)
            return
        if isinstance(event, _ANSWER_TERMINAL_TYPES):
            self._flush_delta(event.answer_id)
        self._require_capacity()
        self._important.append(event)

    def pop(self) -> SerializableEvent | None:
        if self._important:
            return self._important.popleft()
        if self._deltas:
            _, event = self._deltas.popitem(last=False)
            return event
        if self._predictions:
            _, event = self._predictions.popitem(last=False)
            return event
        return None

    def _put_delta(self, event: AnswerDeltaEvent) -> None:
        pending = self._deltas.get(event.answer_id)
        if pending is not None:
            contiguous = event.from_stream_sequence == pending.stream_sequence + 1
            merged_chars = len(pending.text) + len(event.text)
            if contiguous and merged_chars <= self._max_coalesced_delta_chars:
                self._deltas[event.answer_id] = event.model_copy(
                    update={
                        "from_stream_sequence": pending.from_stream_sequence,
                        "text": pending.text + event.text,
                    }
                )
                return
            self._flush_delta(event.answer_id)
        self._require_capacity()
        self._deltas[event.answer_id] = event

    def _flush_delta(self, answer_id: UUID) -> None:
        pending = self._deltas.pop(answer_id, None)
        if pending is not None:
            self._important.append(pending)

    def _put_prediction(self, event: PredictionSnapshotEvent) -> None:
        pending = self._predictions.get(event.prediction_id)
        if pending is not None:
            if event.revision > pending.revision:
                self._predictions[event.prediction_id] = event
            return
        self._require_capacity()
        self._predictions[event.prediction_id] = event

    def _require_capacity(self) -> None:
        if len(self) >= self._max_items:
            raise OutboundBufferFull("browser outbound buffer is full")


class OutboundEventWriter:
    """Only owner of transcribe WebSocket writes for one browser lease."""

    def __init__(
        self,
        websocket: JsonWebSocket,
        *,
        max_items: int = 128,
        max_coalesced_delta_chars: int = 4_096,
    ) -> None:
        self._websocket = websocket
        self._buffer = OutboundEventBuffer(
            max_items=max_items,
            max_coalesced_delta_chars=max_coalesced_delta_chars,
        )
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def task(self) -> asyncio.Task[None]:
        if self._task is None:
            raise RuntimeError("outbound writer has not started")
        return self._task

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    def start(self) -> asyncio.Task[None]:
        if self._task is not None:
            return self._task
        self._task = asyncio.create_task(self._run(), name="websocket-outbound-writer")
        return self._task

    def publish(self, event: SerializableEvent) -> None:
        if self._closed:
            raise RuntimeError("outbound writer is closed")
        try:
            self._buffer.put(event)
        except OutboundBufferFull:
            self._closed = True
            task = self._task
            if task is not None and not task.done():
                task.cancel()
            raise
        self._idle.clear()
        self._wake.set()

    async def drain(self, *, timeout_seconds: float = 1.0) -> None:
        await asyncio.wait_for(self._idle.wait(), timeout=timeout_seconds)

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            event = self._buffer.pop()
            if event is None:
                self._idle.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            await self._websocket.send_json(
                event.model_dump(mode="json", exclude_none=True)
            )
            if len(self._buffer) == 0:
                self._idle.set()
