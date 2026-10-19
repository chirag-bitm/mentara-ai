import asyncio
from collections import deque
from collections.abc import AsyncIterator

import pytest

from app.services.stt.base import (
    STTProviderError,
    STTProviderFatalError,
    STTProviderTransientError,
    TranscriptResult,
)
from app.services.stt.rotation import (
    ProviderLifecycleEvent,
    ProviderLifecycleEventKind,
    RotatingSTTProvider,
    RotationPolicy,
)
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)


class FakeProvider:
    def __init__(
        self,
        *,
        connect_error: Exception | None = None,
        connect_gate: asyncio.Event | None = None,
    ) -> None:
        self.connect_error = connect_error
        self.connect_gate = connect_gate
        self.results_queue: asyncio.Queue[TranscriptResult | Exception | None] = (
            asyncio.Queue()
        )
        self.sent_audio: list[bytes] = []
        self.connected = False
        self.finished = False
        self.closed = False

    async def connect(self) -> None:
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def send_audio(self, audio: bytes) -> None:
        self.sent_audio.append(audio)

    async def finish(self) -> None:
        self.finished = True
        await self.results_queue.put(None)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while True:
            item = await self.results_queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def close(self) -> None:
        self.closed = True

    async def emit(self, text: str, *, final: bool = False) -> None:
        await self.results_queue.put(
            TranscriptResult(
                text=text,
                is_final=final,
                speech_final=final,
            )
        )

    async def fail(self, error: Exception) -> None:
        await self.results_queue.put(error)


class ProviderSequence:
    def __init__(self, *providers: FakeProvider) -> None:
        self.providers = deque(providers)
        self.calls = 0

    def __call__(self) -> FakeProvider:
        self.calls += 1
        return self.providers.popleft()


def policy(
    *,
    interval: float = 0.04,
    final_wait: float = 0.04,
    buffer_chunks: int = 20,
    attempts: int = 3,
) -> RotationPolicy:
    return RotationPolicy(
        rotation_interval_seconds=interval,
        final_boundary_wait_seconds=final_wait,
        audio_buffer_max_chunks=buffer_chunks,
        reconnect_max_attempts=attempts,
        reconnect_base_delay_seconds=0,
        finish_drain_timeout_seconds=0.2,
    )


async def wait_until(predicate, *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=timeout)


async def collect_results(provider: RotatingSTTProvider) -> list[TranscriptResult]:
    return [result async for result in provider.results()]


def test_planned_rotation_waits_for_final_boundary_and_preserves_results() -> None:
    async def scenario() -> None:
        first = FakeProvider()
        second = FakeProvider()
        replacements = ProviderSequence(second)
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=replacements,
            # Leave enough final-boundary headroom for Windows' coarser and
            # occasionally delayed asyncio scheduling.  The test still emits
            # the final result only after rotation is due, so it continues to
            # prove that planned rotation waits for the boundary rather than
            # forcing degraded continuity.
            policy=policy(final_wait=0.5),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))

        await provider.send_audio(b"first")
        await wait_until(lambda: first.sent_audio == [b"first"])
        await first.emit("First", final=False)
        await asyncio.sleep(0.05)
        await first.emit("First sentence.", final=True)

        await wait_until(lambda: provider.generation == 2)
        await provider.send_audio(b"second")
        await wait_until(lambda: second.sent_audio == [b"second"])
        await second.emit("Second sentence.", final=True)
        await provider.finish()
        results = await asyncio.wait_for(collector, timeout=1)
        await provider.close()

        session = TranscriptionSession()
        session.transition(SessionConnectionState.CONNECTED)
        canonical_events = [session.apply(result) for result in results]

        assert [result.text for result in results] == [
            "First",
            "First sentence.",
            "Second sentence.",
        ]
        assert all(event is not None for event in canonical_events)
        assert [event.sequence for event in canonical_events if event is not None] == [
            1,
            2,
            3,
        ]
        assert len(
            {event.session_id for event in canonical_events if event is not None}
        ) == 1
        assert [event.kind for event in events] == [
            ProviderLifecycleEventKind.RECONNECTING,
            ProviderLifecycleEventKind.RECONNECTED,
        ]
        assert first.closed is True
        assert second.finished is True
        assert provider.dropped_audio_chunks == 0

    asyncio.run(scenario())


def test_forced_rotation_reports_degraded_continuity() -> None:
    async def scenario() -> None:
        first = FakeProvider()
        second = FakeProvider()
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=ProviderSequence(second),
            policy=policy(interval=0.01, final_wait=0.01),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))
        await first.emit("Speech still in progress", final=False)
        await wait_until(lambda: provider.generation == 2)

        assert [event.kind for event in events[:3]] == [
            ProviderLifecycleEventKind.DEGRADED,
            ProviderLifecycleEventKind.RECONNECTING,
            ProviderLifecycleEventKind.RECONNECTED,
        ]
        assert events[0].reason == "forced_rotation"

        await provider.finish()
        await asyncio.wait_for(collector, timeout=1)
        await provider.close()

    asyncio.run(scenario())


def test_reconnect_buffer_is_bounded_and_keeps_newest_audio() -> None:
    async def scenario() -> None:
        reconnect_gate = asyncio.Event()
        first = FakeProvider()
        second = FakeProvider(connect_gate=reconnect_gate)
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=ProviderSequence(second),
            policy=policy(interval=0.01, final_wait=0, buffer_chunks=2),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))
        await wait_until(
            lambda: any(
                event.kind is ProviderLifecycleEventKind.RECONNECTING
                for event in events
            )
        )

        for chunk in (b"one", b"two", b"three", b"four"):
            await provider.send_audio(chunk)

        assert provider.buffered_audio_chunks == 2
        assert provider.dropped_audio_chunks == 2
        overflow_events = [
            event for event in events if event.reason == "audio_buffer_overflow"
        ]
        assert len(overflow_events) == 1

        reconnect_gate.set()
        await wait_until(lambda: provider.generation == 2)
        await wait_until(lambda: second.sent_audio == [b"three", b"four"])
        await provider.finish()
        await asyncio.wait_for(collector, timeout=1)
        await provider.close()

    asyncio.run(scenario())


def test_transient_interruption_retries_with_bounded_attempts() -> None:
    async def scenario() -> None:
        first = FakeProvider()
        failed_replacement = FakeProvider(
            connect_error=STTProviderTransientError("temporary network failure")
        )
        recovered = FakeProvider()
        replacements = ProviderSequence(failed_replacement, recovered)
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=replacements,
            policy=policy(interval=10, attempts=2),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))
        await first.fail(STTProviderTransientError("socket reset"))
        await wait_until(lambda: provider.generation == 2)

        assert replacements.calls == 2
        assert failed_replacement.closed is True
        assert [event.kind for event in events] == [
            ProviderLifecycleEventKind.DEGRADED,
            ProviderLifecycleEventKind.RECONNECTING,
            ProviderLifecycleEventKind.RECONNECTED,
        ]

        await provider.finish()
        await asyncio.wait_for(collector, timeout=1)
        await provider.close()

    asyncio.run(scenario())


def test_fatal_provider_error_stops_without_retrying() -> None:
    async def scenario() -> None:
        first = FakeProvider()
        unused_replacement = FakeProvider()
        replacements = ProviderSequence(unused_replacement)
        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=replacements,
            policy=policy(interval=10),
        )
        await provider.connect()
        await first.fail(STTProviderFatalError("quota exhausted"))

        with pytest.raises(STTProviderFatalError, match="quota exhausted"):
            await asyncio.wait_for(collect_results(provider), timeout=1)

        assert replacements.calls == 0
        await provider.close()

    asyncio.run(scenario())


def test_retry_exhaustion_surfaces_one_terminal_error() -> None:
    async def scenario() -> None:
        first = FakeProvider()
        retry_one = FakeProvider(
            connect_error=STTProviderTransientError("temporary one")
        )
        retry_two = FakeProvider(
            connect_error=STTProviderTransientError("temporary two")
        )
        replacements = ProviderSequence(retry_one, retry_two)
        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=replacements,
            policy=policy(interval=10, attempts=2),
        )
        await provider.connect()
        await first.fail(STTProviderTransientError("socket reset"))

        with pytest.raises(STTProviderError, match="failed after 2 attempts"):
            await asyncio.wait_for(collect_results(provider), timeout=1)

        assert replacements.calls == 2
        await provider.close()

    asyncio.run(scenario())


def test_stop_during_reconnect_cancels_replacement_without_error() -> None:
    async def scenario() -> None:
        reconnect_gate = asyncio.Event()
        first = FakeProvider()
        blocked_replacement = FakeProvider(connect_gate=reconnect_gate)
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=ProviderSequence(blocked_replacement),
            policy=policy(interval=0.01, final_wait=0),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))
        await wait_until(
            lambda: any(
                event.kind is ProviderLifecycleEventKind.RECONNECTING
                for event in events
            )
        )

        await asyncio.wait_for(provider.finish(), timeout=1)
        assert await asyncio.wait_for(collector, timeout=1) == []
        assert blocked_replacement.closed is True
        assert provider.generation == 1
        await provider.close()

    asyncio.run(scenario())


def test_close_during_replacement_connect_cancels_and_closes_provider() -> None:
    async def scenario() -> None:
        reconnect_gate = asyncio.Event()
        first = FakeProvider()
        blocked_replacement = FakeProvider(connect_gate=reconnect_gate)
        events: list[ProviderLifecycleEvent] = []

        async def on_lifecycle(event: ProviderLifecycleEvent) -> None:
            events.append(event)

        provider = RotatingSTTProvider(
            initial_provider=first,
            provider_factory=ProviderSequence(blocked_replacement),
            policy=policy(interval=0.01, final_wait=0),
            lifecycle_callback=on_lifecycle,
        )
        await provider.connect()
        collector = asyncio.create_task(collect_results(provider))
        await wait_until(
            lambda: any(
                event.kind is ProviderLifecycleEventKind.RECONNECTING
                for event in events
            )
        )

        await asyncio.wait_for(provider.close(), timeout=1)
        assert await asyncio.wait_for(collector, timeout=1) == []
        assert first.closed is True
        assert blocked_replacement.closed is True

    asyncio.run(scenario())
