from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from app.services.conversation.engine import ConversationTurnEngine, TurnEngineUpdate
from app.services.conversation.models import (
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import CanonicalUtterance


TurnCallback = Callable[[ConversationTurn], Awaitable[None]]
Clock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]


async def _ignore_turn(_turn: ConversationTurn) -> None:
    return None


class ConversationTurnRuntime:
    """Owns the engine's single cancellable deadline task for one browser lease."""

    def __init__(
        self,
        *,
        engine: ConversationTurnEngine,
        clock: Clock,
        on_turn_finalized: TurnCallback = _ignore_turn,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._engine = engine
        self._clock = clock
        self._on_turn_finalized = on_turn_finalized
        self._sleeper = sleeper
        self._deadline_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def pending_task_count(self) -> int:
        task = self._deadline_task
        return int(task is not None and not task.done())

    async def observe(
        self,
        utterance: CanonicalUtterance,
        *,
        continuity_quality: ContinuityQuality,
    ) -> TurnEngineUpdate:
        async with self._lock:
            update = self._engine.observe(
                utterance,
                continuity_quality=continuity_quality,
            )
            self._schedule_deadline_locked()
        for turn in update.finalized_turns:
            await self._on_turn_finalized(turn)
        return update

    async def resume(self) -> None:
        async with self._lock:
            self._schedule_deadline_locked()

    async def pause(self) -> None:
        await self._cancel_deadline_task()

    async def flush(self, *, reason: TurnFinalizationReason) -> ConversationTurn | None:
        await self._cancel_deadline_task()
        async with self._lock:
            turn = self._engine.flush(now_ms=self._clock(), reason=reason)
        if turn is not None:
            await self._on_turn_finalized(turn)
        return turn

    async def cancel(self) -> None:
        await self._cancel_deadline_task()
        async with self._lock:
            self._engine.cancel_active()

    def _schedule_deadline_locked(self) -> None:
        deadline = self._engine.pending_deadline_ms
        current = self._deadline_task
        if current is not None and not current.done():
            current.cancel()
        self._deadline_task = None
        if deadline is not None:
            self._deadline_task = asyncio.create_task(
                self._run_deadline(deadline)
            )

    async def _run_deadline(self, deadline_ms: int) -> None:
        try:
            delay_seconds = max(0, deadline_ms - self._clock()) / 1_000
            await self._sleeper(delay_seconds)
            async with self._lock:
                if self._engine.pending_deadline_ms != deadline_ms:
                    return
                turn = self._engine.finalize_due(now_ms=max(self._clock(), deadline_ms))
                self._deadline_task = None
            if turn is not None:
                await self._on_turn_finalized(turn)
        except asyncio.CancelledError:
            raise

    async def _cancel_deadline_task(self) -> None:
        async with self._lock:
            task = self._deadline_task
            self._deadline_task = None
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            with suppress(asyncio.CancelledError):
                await task
