import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum

from app.services.stt.base import (
    STTProvider,
    STTProviderError,
    STTProviderTransientError,
    TranscriptResult,
)


class ProviderLifecycleEventKind(str, Enum):
    RECONNECTING = "reconnecting"
    RECONNECTED = "reconnected"
    DEGRADED = "degraded"


@dataclass(slots=True, frozen=True)
class ProviderLifecycleEvent:
    kind: ProviderLifecycleEventKind
    generation: int
    reason: str
    message: str


@dataclass(slots=True, frozen=True)
class RotationPolicy:
    rotation_interval_seconds: float = 540.0
    final_boundary_wait_seconds: float = 10.0
    audio_buffer_max_chunks: int = 20
    reconnect_max_attempts: int = 3
    reconnect_base_delay_seconds: float = 0.25
    finish_drain_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.rotation_interval_seconds <= 0:
            raise ValueError("rotation_interval_seconds must be positive")
        if self.final_boundary_wait_seconds < 0:
            raise ValueError("final_boundary_wait_seconds must not be negative")
        if self.audio_buffer_max_chunks <= 0:
            raise ValueError("audio_buffer_max_chunks must be positive")
        if self.reconnect_max_attempts <= 0:
            raise ValueError("reconnect_max_attempts must be positive")
        if self.reconnect_base_delay_seconds < 0:
            raise ValueError("reconnect_base_delay_seconds must not be negative")
        if self.finish_drain_timeout_seconds <= 0:
            raise ValueError("finish_drain_timeout_seconds must be positive")


ProviderFactory = Callable[[], STTProvider]
LifecycleCallback = Callable[[ProviderLifecycleEvent], Awaitable[None]]


class _BoundedAudioBuffer:
    """In-memory FIFO that never stores more than the configured audio window."""

    def __init__(self, max_chunks: int) -> None:
        self._max_chunks = max_chunks
        self._chunks: deque[bytes] = deque()
        self._in_flight = 0
        self._condition = asyncio.Condition()

    async def put(self, audio: bytes) -> bool:
        async with self._condition:
            dropped = len(self._chunks) >= self._max_chunks
            if dropped:
                self._chunks.popleft()
            self._chunks.append(audio)
            self._condition.notify_all()
            return dropped

    async def get(self) -> bytes:
        async with self._condition:
            await self._condition.wait_for(lambda: bool(self._chunks))
            audio = self._chunks.popleft()
            self._in_flight += 1
            return audio

    async def mark_sent(self) -> None:
        async with self._condition:
            self._in_flight -= 1
            self._condition.notify_all()

    async def requeue_front(self, audio: bytes) -> bool:
        async with self._condition:
            self._in_flight -= 1
            dropped = len(self._chunks) >= self._max_chunks
            if dropped:
                self._chunks.pop()
            self._chunks.appendleft(audio)
            self._condition.notify_all()
            return dropped

    async def wait_drained(self) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._chunks and self._in_flight == 0
            )

    async def discard_pending(self) -> int:
        async with self._condition:
            count = len(self._chunks)
            self._chunks.clear()
            self._condition.notify_all()
            return count

    @property
    def size(self) -> int:
        return len(self._chunks)


class _FinalBoundaryTracker:
    def __init__(self) -> None:
        self._count = 0
        self._active_utterance = False
        self._condition = asyncio.Condition()

    async def observe(self, result: TranscriptResult) -> None:
        async with self._condition:
            if result.is_final:
                self._active_utterance = False
                self._count += 1
                self._condition.notify_all()
            else:
                self._active_utterance = True

    async def wait_until_safe(self, *, timeout: float) -> None:
        async with self._condition:
            if not self._active_utterance:
                return

            observed_count = self._count
            await asyncio.wait_for(
                self._condition.wait_for(lambda: self._count > observed_count),
                timeout=timeout,
            )


@dataclass(slots=True, frozen=True)
class _ResultFailure:
    error: STTProviderError


class _ResultEnd:
    pass


RESULT_END = _ResultEnd()


class _GenerationOutcomeKind(str, Enum):
    ROTATE = "rotate"
    FAILURE = "failure"
    FINISH = "finish"


@dataclass(slots=True, frozen=True)
class _GenerationOutcome:
    kind: _GenerationOutcomeKind
    error: BaseException | None = None
    safe_boundary: bool = True


class RotatingSTTProvider:
    """Keeps one STT interface while replacing finite-lived provider sockets."""

    def __init__(
        self,
        *,
        initial_provider: STTProvider,
        provider_factory: ProviderFactory,
        policy: RotationPolicy,
        lifecycle_callback: LifecycleCallback | None = None,
    ) -> None:
        self._initial_provider = initial_provider
        self._provider_factory = provider_factory
        self._policy = policy
        self._lifecycle_callback = lifecycle_callback
        self._audio_buffer = _BoundedAudioBuffer(policy.audio_buffer_max_chunks)
        self._result_queue: asyncio.Queue[
            TranscriptResult | _ResultFailure | _ResultEnd
        ] = asyncio.Queue()
        self._finish_requested = asyncio.Event()
        self._finish_sent = asyncio.Event()
        self._send_gate = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._manager_task: asyncio.Task[None] | None = None
        self._current_provider: STTProvider | None = None
        self._terminal_error: STTProviderError | None = None
        self._generation = 0
        self._dropped_audio_chunks = 0
        self._degraded_reasons: set[str] = set()
        self._closed = False
        self._results_closed = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def dropped_audio_chunks(self) -> int:
        return self._dropped_audio_chunks

    @property
    def buffered_audio_chunks(self) -> int:
        return self._audio_buffer.size

    async def connect(self) -> None:
        if self._closed:
            raise STTProviderError("The rotating STT provider is closed.")
        if self._manager_task is not None:
            raise STTProviderError("The rotating STT provider is already connected.")

        provider = self._initial_provider
        try:
            await provider.connect()
        except Exception:
            await provider.close()
            raise

        self._current_provider = provider
        self._generation = 1
        self._send_gate.set()
        self._manager_task = asyncio.create_task(self._manager_loop(provider))

    async def send_audio(self, audio: bytes) -> None:
        if self._terminal_error is not None:
            raise self._terminal_error
        if self._closed or self._finish_requested.is_set():
            raise STTProviderError(
                "The transcription stream is no longer accepting audio."
            )

        dropped = await self._audio_buffer.put(audio)
        if dropped:
            self._dropped_audio_chunks += 1
            await self._emit_degraded(
                reason="audio_buffer_overflow",
                message=(
                    "The reconnect audio buffer filled; a small amount of recent "
                    "audio may be missing."
                ),
            )

    async def finish(self) -> None:
        if self._manager_task is None or self._closed:
            return
        self._finish_requested.set()
        await self._finish_sent.wait()
        if self._terminal_error is not None:
            raise self._terminal_error

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while True:
            item = await self._result_queue.get()
            if isinstance(item, TranscriptResult):
                yield item
                continue
            if isinstance(item, _ResultFailure):
                raise item.error
            return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._send_gate.clear()

        if self._manager_task is not None and not self._manager_task.done():
            self._manager_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._manager_task

        if self._current_provider is not None:
            await self._current_provider.close()
            self._current_provider = None

        self._finish_sent.set()
        self._publish_end()

    async def _manager_loop(self, provider: STTProvider) -> None:
        try:
            while True:
                outcome = await self._run_generation(provider)
                if outcome.kind is _GenerationOutcomeKind.FINISH:
                    await provider.close()
                    self._current_provider = None
                    self._publish_end()
                    return

                if outcome.kind is _GenerationOutcomeKind.FAILURE:
                    error = outcome.error
                    if not self._is_transient(error):
                        raise self._normalize_error(error)
                    await self._emit_degraded(
                        reason="provider_interruption",
                        message=(
                            "The STT connection was interrupted; recent audio may "
                            "be incomplete while Mentara reconnects."
                        ),
                    )
                elif not outcome.safe_boundary:
                    await self._emit_degraded(
                        reason="forced_rotation",
                        message=(
                            "Mentara rotated the STT connection without a final "
                            "speech boundary; recent words may be incomplete."
                        ),
                    )

                await self._emit(
                    ProviderLifecycleEventKind.RECONNECTING,
                    reason=(
                        "planned_rotation"
                        if outcome.kind is _GenerationOutcomeKind.ROTATE
                        else "provider_interruption"
                    ),
                    message="Refreshing the streaming STT connection…",
                )
                await provider.close()
                self._current_provider = None
                replacement = await self._connect_replacement()
                if replacement is None:
                    self._publish_end()
                    return
                provider = replacement
                self._current_provider = provider
                self._generation += 1
                self._degraded_reasons.clear()
                self._send_gate.set()
                await self._emit(
                    ProviderLifecycleEventKind.RECONNECTED,
                    reason="replacement_connected",
                    message="Streaming STT reconnected.",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = self._normalize_error(exc)
            self._terminal_error = error
            self._result_queue.put_nowait(_ResultFailure(error))
        finally:
            self._finish_sent.set()

    async def _run_generation(self, provider: STTProvider) -> _GenerationOutcome:
        final_boundary = _FinalBoundaryTracker()
        sender = asyncio.create_task(self._send_audio_loop(provider))
        receiver = asyncio.create_task(
            self._receive_results_loop(provider, final_boundary)
        )
        rotation = asyncio.create_task(self._wait_for_rotation(final_boundary))
        finish = asyncio.create_task(self._finish_requested.wait())
        tasks = {sender, receiver, rotation, finish}

        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if finish in done and finish.result():
                rotation.cancel()
                await self._finish_generation(provider, sender, receiver)
                return _GenerationOutcome(_GenerationOutcomeKind.FINISH)

            if rotation in done:
                safe_boundary = rotation.result()
                await self._stop_sender(sender)
                receiver.cancel()
                with suppress(asyncio.CancelledError):
                    await receiver
                return _GenerationOutcome(
                    _GenerationOutcomeKind.ROTATE,
                    safe_boundary=safe_boundary,
                )

            failed_task = sender if sender in done else receiver
            error = self._task_error(failed_task)
            await self._stop_sender(sender)
            if not receiver.done():
                receiver.cancel()
                with suppress(asyncio.CancelledError):
                    await receiver
            return _GenerationOutcome(
                _GenerationOutcomeKind.FAILURE,
                error=error,
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def _send_audio_loop(self, provider: STTProvider) -> None:
        while True:
            await self._send_gate.wait()
            audio = await self._audio_buffer.get()
            try:
                async with self._send_lock:
                    if not self._send_gate.is_set():
                        dropped = await self._audio_buffer.requeue_front(audio)
                        audio = b""
                        if dropped:
                            await self._record_requeue_overflow()
                        continue
                    await provider.send_audio(audio)
                await self._audio_buffer.mark_sent()
                audio = b""
            except asyncio.CancelledError:
                if audio:
                    dropped = await self._audio_buffer.requeue_front(audio)
                    if dropped:
                        await self._record_requeue_overflow()
                raise
            except Exception:
                if audio:
                    dropped = await self._audio_buffer.requeue_front(audio)
                    if dropped:
                        await self._record_requeue_overflow()
                raise

    async def _receive_results_loop(
        self,
        provider: STTProvider,
        final_boundary: _FinalBoundaryTracker,
    ) -> None:
        async for result in provider.results():
            await self._result_queue.put(result)
            await final_boundary.observe(result)

        if not self._finish_requested.is_set():
            raise STTProviderTransientError(
                "The STT provider ended the stream unexpectedly."
            )

    async def _wait_for_rotation(
        self,
        final_boundary: _FinalBoundaryTracker,
    ) -> bool:
        await asyncio.sleep(self._policy.rotation_interval_seconds)
        try:
            await final_boundary.wait_until_safe(
                timeout=self._policy.final_boundary_wait_seconds,
            )
            return True
        except TimeoutError:
            return False

    async def _finish_generation(
        self,
        provider: STTProvider,
        sender: asyncio.Task[None],
        receiver: asyncio.Task[None],
    ) -> None:
        try:
            await asyncio.wait_for(
                self._audio_buffer.wait_drained(),
                timeout=self._policy.finish_drain_timeout_seconds,
            )
        except TimeoutError:
            await self._emit_degraded(
                reason="finish_drain_timeout",
                message=(
                    "Mentara could not flush all buffered audio before stopping; "
                    "the final words may be incomplete."
                ),
            )
            await self._audio_buffer.discard_pending()

        await self._stop_sender(sender)
        try:
            await provider.finish()
        finally:
            self._finish_sent.set()

        await receiver

    async def _stop_sender(self, sender: asyncio.Task[None]) -> None:
        self._send_gate.clear()
        async with self._send_lock:
            pass
        if not sender.done():
            sender.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await sender

    async def _connect_replacement(self) -> STTProvider | None:
        last_error: BaseException | None = None
        for attempt in range(1, self._policy.reconnect_max_attempts + 1):
            if self._finish_requested.is_set():
                return None

            provider = self._provider_factory()
            connect_task = asyncio.create_task(provider.connect())
            finish_task = asyncio.create_task(self._finish_requested.wait())
            connected = False
            try:
                done, _ = await asyncio.wait(
                    {connect_task, finish_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if finish_task in done and finish_task.result():
                    return None

                await connect_task
                connected = True
                return provider
            except Exception as exc:
                last_error = exc
                if not self._is_transient(exc):
                    raise self._normalize_error(exc) from exc
                if attempt < self._policy.reconnect_max_attempts:
                    delay = self._policy.reconnect_base_delay_seconds * (
                        2 ** (attempt - 1)
                    )
                    try:
                        await asyncio.wait_for(
                            self._finish_requested.wait(),
                            timeout=delay,
                        )
                        return None
                    except TimeoutError:
                        pass
            finally:
                if not connect_task.done():
                    connect_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await connect_task
                if not finish_task.done():
                    finish_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await finish_task
                if not connected:
                    with suppress(Exception):
                        await provider.close()

        raise STTProviderError(
            "Streaming STT reconnection failed after "
            f"{self._policy.reconnect_max_attempts} attempts."
        ) from last_error

    async def _record_requeue_overflow(self) -> None:
        self._dropped_audio_chunks += 1
        await self._emit_degraded(
            reason="audio_buffer_overflow",
            message=(
                "The reconnect audio buffer filled; a small amount of recent "
                "audio may be missing."
            ),
        )

    async def _emit_degraded(self, *, reason: str, message: str) -> None:
        if reason in self._degraded_reasons:
            return
        self._degraded_reasons.add(reason)
        await self._emit(
            ProviderLifecycleEventKind.DEGRADED,
            reason=reason,
            message=message,
        )

    async def _emit(
        self,
        kind: ProviderLifecycleEventKind,
        *,
        reason: str,
        message: str,
    ) -> None:
        if self._lifecycle_callback is None:
            return
        await self._lifecycle_callback(
            ProviderLifecycleEvent(
                kind=kind,
                generation=self._generation,
                reason=reason,
                message=message,
            )
        )

    @staticmethod
    def _task_error(task: asyncio.Task[object]) -> BaseException:
        if task.cancelled():
            return STTProviderTransientError("The STT provider task was cancelled.")
        error = task.exception()
        if error is not None:
            return error
        return STTProviderTransientError("The STT provider ended unexpectedly.")

    @staticmethod
    def _is_transient(error: BaseException | None) -> bool:
        return isinstance(
            error,
            (STTProviderTransientError, OSError, TimeoutError),
        )

    @staticmethod
    def _normalize_error(error: BaseException | None) -> STTProviderError:
        if isinstance(error, STTProviderError):
            return error
        if isinstance(error, (OSError, TimeoutError)):
            return STTProviderTransientError(
                "The streaming STT connection was interrupted."
            )
        if error is None:
            return STTProviderError("The streaming STT provider failed.")
        return STTProviderError("The streaming STT provider failed unexpectedly.")

    def _publish_end(self) -> None:
        if self._results_closed:
            return
        self._results_closed = True
        self._result_queue.put_nowait(RESULT_END)
