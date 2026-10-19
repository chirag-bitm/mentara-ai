import asyncio
from uuid import UUID

import pytest

from app.api.outbound import (
    OutboundBufferFull,
    OutboundEventBuffer,
    OutboundEventWriter,
)
from app.schemas.events import (
    AnswerCompletedEvent,
    AnswerDeltaEvent,
    AnswerStartedEvent,
    PredictionSnapshotEvent,
    StatusEvent,
)


ANSWER_ID = UUID("20000000-0000-0000-0000-000000000001")
SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
PREDICTION_ID = UUID("50000000-0000-0000-0000-000000000001")


def _common(*, revision: int, stream_sequence: int) -> dict[str, object]:
    return {
        "answer_id": ANSWER_ID,
        "session_id": SESSION_ID,
        "detection_id": UUID("30000000-0000-0000-0000-000000000001"),
        "source_turn_id": UUID("40000000-0000-0000-0000-000000000001"),
        "source_turn_sequence": 1,
        "attempt": 1,
        "revision": revision,
        "stream_sequence": stream_sequence,
    }


def _delta(sequence: int, text: str) -> AnswerDeltaEvent:
    return AnswerDeltaEvent(
        **_common(revision=sequence + 2, stream_sequence=sequence),
        from_stream_sequence=sequence,
        text=text,
        first_text_ms=110,
        answer_request_to_first_text_ms=10,
        question_detected_to_first_text_ms=12,
    )


def _prediction(revision: int, *, state: str = "scheduled") -> PredictionSnapshotEvent:
    return PredictionSnapshotEvent(
        prediction_id=PREDICTION_ID,
        session_id=SESSION_ID,
        active_turn_id=UUID("60000000-0000-0000-0000-000000000001"),
        active_turn_sequence=1,
        input_revision=max(1, revision),
        attempt=0,
        state=state,
        revision=revision,
        audio_source="microphone",
        speaker_role="local_user",
        continuity_quality="normal",
        active_turn_awaiting_finalization=False,
        candidate_consistent_revision_count=0,
        candidates=[],
        input_observed_ms=100 + revision,
        scheduled_ms=100 + revision,
        terminal_ms=100 + revision if state == "invalidated" else None,
        invalidation_reason=("active_input_changed" if state == "invalidated" else None),
    )


def test_answer_deltas_coalesce_but_important_events_keep_priority() -> None:
    buffer = OutboundEventBuffer(max_items=4, max_coalesced_delta_chars=20)
    started = AnswerStartedEvent(
        **_common(revision=2, stream_sequence=0),
        requested_ms=100,
        provider_started_ms=102,
        question_detected_to_answer_request_ms=1,
        answer_request_to_provider_start_ms=2,
    )
    status = StatusEvent(status="ready", message="Ready")
    buffer.put(started)
    buffer.put(_delta(1, "small "))
    buffer.put(_delta(2, "chunks"))
    buffer.put(status)

    assert len(buffer) == 3
    assert buffer.pop() is started
    assert buffer.pop() is status
    merged = buffer.pop()
    assert isinstance(merged, AnswerDeltaEvent)
    assert merged.from_stream_sequence == 1
    assert merged.stream_sequence == 2
    assert merged.text == "small chunks"


def test_tiny_delta_flood_coalesces_and_cannot_starve_status() -> None:
    buffer = OutboundEventBuffer(max_items=8, max_coalesced_delta_chars=2_000)
    for sequence in range(1, 1_001):
        buffer.put(_delta(sequence, "x"))
    status = StatusEvent(status="degraded", message="critical status")
    buffer.put(status)

    assert len(buffer) == 2
    assert buffer.pop() is status
    merged = buffer.pop()
    assert isinstance(merged, AnswerDeltaEvent)
    assert merged.from_stream_sequence == 1
    assert merged.stream_sequence == 1_000
    assert merged.text == "x" * 1_000


def test_prediction_revision_flood_coalesces_and_cannot_starve_status() -> None:
    buffer = OutboundEventBuffer(max_items=3, max_coalesced_delta_chars=20)
    for revision in range(1, 1_001):
        buffer.put(_prediction(revision))
    status = StatusEvent(status="degraded", message="critical status")
    buffer.put(status)

    assert len(buffer) == 2
    assert buffer.pop() is status
    latest = buffer.pop()
    assert isinstance(latest, PredictionSnapshotEvent)
    assert latest.revision == 1_000


def test_newer_prediction_invalidation_replaces_pending_ready_state() -> None:
    buffer = OutboundEventBuffer(max_items=2, max_coalesced_delta_chars=20)
    buffer.put(_prediction(2))
    buffer.put(_prediction(3, state="invalidated"))

    latest = buffer.pop()
    assert isinstance(latest, PredictionSnapshotEvent)
    assert latest.state == "invalidated"
    assert latest.revision == 3


def test_terminal_event_flushes_pending_delta_before_terminal() -> None:
    buffer = OutboundEventBuffer(max_items=4, max_coalesced_delta_chars=20)
    delta = _delta(1, "final text")
    completed = AnswerCompletedEvent(
        **_common(revision=4, stream_sequence=1),
        terminal_ms=150,
        answer_generation_total_ms=50,
    )
    buffer.put(delta)
    buffer.put(completed)

    assert buffer.pop() == delta
    assert buffer.pop() == completed


def test_buffer_is_bounded_even_when_browser_is_slow() -> None:
    buffer = OutboundEventBuffer(max_items=2, max_coalesced_delta_chars=20)
    buffer.put(_delta(1, "a"))
    buffer.put(StatusEvent(status="ready", message="one"))
    with pytest.raises(OutboundBufferFull):
        buffer.put(StatusEvent(status="degraded", message="two"))
    assert len(buffer) == 2


class _RecordingWebSocket:
    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.gate = gate
        self.entered = asyncio.Event()
        self.sent: list[object] = []
        self.concurrent_sends = 0
        self.max_concurrent_sends = 0

    async def send_json(self, data: object) -> None:
        self.concurrent_sends += 1
        self.max_concurrent_sends = max(
            self.max_concurrent_sends,
            self.concurrent_sends,
        )
        self.entered.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(0)
            self.sent.append(data)
        finally:
            self.concurrent_sends -= 1


def test_writer_serializes_all_websocket_sends_and_drains() -> None:
    async def scenario() -> None:
        websocket = _RecordingWebSocket()
        writer = OutboundEventWriter(websocket, max_items=8)
        writer.start()
        for index in range(5):
            writer.publish(StatusEvent(status="ready", message=str(index)))
        await writer.drain()
        await writer.close()

        assert websocket.max_concurrent_sends == 1
        assert [event["message"] for event in websocket.sent] == [
            "0",
            "1",
            "2",
            "3",
            "4",
        ]
        assert writer.task.done()

    asyncio.run(scenario())


def test_slow_browser_overflow_cancels_writer_without_growth() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        websocket = _RecordingWebSocket(gate)
        writer = OutboundEventWriter(websocket, max_items=2)
        writer.start()
        writer.publish(StatusEvent(status="ready", message="sending"))
        await websocket.entered.wait()

        writer.publish(StatusEvent(status="ready", message="queued-1"))
        writer.publish(_delta(1, "queued-2"))
        with pytest.raises(OutboundBufferFull):
            writer.publish(StatusEvent(status="degraded", message="overflow"))

        await writer.close()
        assert writer.buffered_count == 2
        assert writer.task.done()
        assert websocket.max_concurrent_sends == 1

    asyncio.run(scenario())
