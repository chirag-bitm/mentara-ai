from collections.abc import Callable
from uuid import UUID

from app.services.stt.base import TranscriptResult
from app.services.transcript.aggregator import TranscriptAggregator
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ONE = UUID("00000000-0000-0000-0000-000000000001")
SESSION_TWO = UUID("00000000-0000-0000-0000-000000000002")
UTTERANCE_ONE = UUID("10000000-0000-0000-0000-000000000001")
UTTERANCE_TWO = UUID("10000000-0000-0000-0000-000000000002")


class FakeClock:
    def __init__(self) -> None:
        self.milliseconds = 100_000

    def __call__(self) -> int:
        return self.milliseconds

    def advance(self, milliseconds: int) -> None:
        self.milliseconds += milliseconds


def id_factory(*values: UUID) -> Callable[[], UUID]:
    remaining = iter(values)
    return lambda: next(remaining)


def provider_result(
    text: str,
    *,
    is_final: bool = False,
    confidence: float | None = None,
) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        is_final=is_final,
        speech_final=is_final,
        confidence=confidence,
    )


def make_aggregator(clock: FakeClock, *utterance_ids: UUID) -> TranscriptAggregator:
    return TranscriptAggregator(
        session_id=SESSION_ONE,
        clock=clock,
        utterance_id_factory=id_factory(*utterance_ids),
    )


def test_first_partial_creates_canonical_utterance() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)

    event = aggregator.apply(provider_result("  Can you  "))

    assert event is not None
    assert event.session_id == SESSION_ONE
    assert event.utterance_id == UTTERANCE_ONE
    assert event.sequence == 1
    assert event.revision == 1
    assert event.audio_source is AudioSource.MICROPHONE
    assert event.speaker_role is SpeakerRole.LOCAL_USER
    assert event.text == "Can you"
    assert event.is_final is False
    assert event.first_seen_ms == 0
    assert event.last_updated_ms == 0
    assert event.finalized_ms is None


def test_corrected_partial_reuses_id_and_increments_revision() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    first = aggregator.apply(provider_result("Can you"))
    clock.advance(125)

    corrected = aggregator.apply(provider_result("Can you explain"))

    assert first is not None
    assert corrected is not None
    assert corrected.utterance_id == first.utterance_id
    assert corrected.sequence == 2
    assert corrected.revision == 2
    assert corrected.first_seen_ms == 0
    assert corrected.last_updated_ms == 125


def test_identical_partial_is_suppressed_without_advancing_state() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    first = aggregator.apply(provider_result("Can you explain"))
    clock.advance(100)

    duplicate = aggregator.apply(provider_result("Can you explain"))
    snapshot = aggregator.snapshot()

    assert first is not None
    assert duplicate is None
    assert snapshot.sequence == 1
    assert snapshot.active_utterance == first


def test_final_after_partial_keeps_id_and_records_finalization() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    partial = aggregator.apply(provider_result("Can you explain Redis"))
    clock.advance(500)

    final = aggregator.apply(
        provider_result("Can you explain Redis?", is_final=True)
    )
    snapshot = aggregator.snapshot()

    assert partial is not None
    assert final is not None
    assert final.utterance_id == partial.utterance_id
    assert final.sequence == 2
    assert final.revision == 2
    assert final.is_final is True
    assert final.first_seen_ms == 0
    assert final.last_updated_ms == 500
    assert final.finalized_ms == 500
    assert snapshot.active_utterance is None
    assert snapshot.finalized_utterances == (final,)


def test_finalization_increments_revision_when_text_is_unchanged() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    partial = aggregator.apply(provider_result("Same text"))
    clock.advance(300)

    final = aggregator.apply(provider_result("Same text", is_final=True))

    assert partial is not None
    assert final is not None
    assert final.utterance_id == partial.utterance_id
    assert final.text == partial.text
    assert final.sequence == 2
    assert final.revision == 2
    assert final.is_final is True


def test_final_without_partial_creates_one_final_utterance() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)

    final = aggregator.apply(
        provider_result("Standalone final", is_final=True, confidence=0.92)
    )

    assert final is not None
    assert final.utterance_id == UTTERANCE_ONE
    assert final.sequence == 1
    assert final.revision == 1
    assert final.is_final is True
    assert final.first_seen_ms == 0
    assert final.last_updated_ms == 0
    assert final.finalized_ms == 0
    assert final.confidence == 0.92


def test_duplicate_final_inside_window_is_suppressed() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    first = aggregator.apply(provider_result("Done.", is_final=True))
    clock.advance(400)

    duplicate = aggregator.apply(provider_result("Done.", is_final=True))
    snapshot = aggregator.snapshot()

    assert first is not None
    assert duplicate is None
    assert snapshot.sequence == 1
    assert snapshot.finalized_utterances == (first,)


def test_same_final_after_duplicate_window_is_a_new_utterance() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE, UTTERANCE_TWO)
    first = aggregator.apply(provider_result("Yes.", is_final=True))
    clock.advance(1_001)

    repeated = aggregator.apply(provider_result("Yes.", is_final=True))

    assert first is not None
    assert repeated is not None
    assert repeated.utterance_id == UTTERANCE_TWO
    assert repeated.utterance_id != first.utterance_id
    assert repeated.sequence == 2
    assert repeated.revision == 1


def test_exact_late_partial_after_final_is_safely_suppressed() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)
    aggregator.apply(provider_result("Final text", is_final=True))
    clock.advance(250)

    late_partial = aggregator.apply(provider_result("Final text"))

    assert late_partial is None
    assert aggregator.snapshot().sequence == 1


def test_independent_next_utterance_gets_new_id() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE, UTTERANCE_TWO)
    first = aggregator.apply(provider_result("First.", is_final=True))
    clock.advance(200)

    second = aggregator.apply(provider_result("Second"))

    assert first is not None
    assert second is not None
    assert second.utterance_id == UTTERANCE_TWO
    assert second.utterance_id != first.utterance_id
    assert second.sequence == 2
    assert second.revision == 1


def test_empty_and_whitespace_events_are_ignored() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE)

    assert aggregator.apply(provider_result("")) is None
    assert aggregator.apply(provider_result("   \r\n\t", is_final=True)) is None
    assert aggregator.snapshot().sequence == 0
    assert aggregator.snapshot().active_utterance is None
    assert aggregator.snapshot().finalized_utterances == ()


def test_sequence_and_revision_are_monotonic_for_real_changes() -> None:
    clock = FakeClock()
    aggregator = make_aggregator(clock, UTTERANCE_ONE, UTTERANCE_TWO)

    first = aggregator.apply(provider_result("Can"))
    corrected = aggregator.apply(provider_result("Can you"))
    duplicate = aggregator.apply(provider_result("Can you"))
    final = aggregator.apply(provider_result("Can you?", is_final=True))
    next_final = aggregator.apply(provider_result("Yes.", is_final=True))

    assert duplicate is None
    assert [event.sequence for event in (first, corrected, final, next_final) if event] == [
        1,
        2,
        3,
        4,
    ]
    assert [event.revision for event in (first, corrected, final) if event] == [1, 2, 3]
    assert next_final is not None
    assert next_final.revision == 1


def test_reset_starts_a_new_session_with_empty_state_and_clock() -> None:
    clock = FakeClock()
    aggregator = TranscriptAggregator(
        session_id=SESSION_ONE,
        clock=clock,
        session_id_factory=id_factory(SESSION_TWO),
        utterance_id_factory=id_factory(UTTERANCE_ONE, UTTERANCE_TWO),
    )
    aggregator.apply(provider_result("Old session", is_final=True))
    clock.advance(2_000)

    reset_snapshot = aggregator.reset()
    first_new_event = aggregator.apply(provider_result("New session"))

    assert reset_snapshot.session_id == SESSION_TWO
    assert reset_snapshot.sequence == 0
    assert reset_snapshot.active_utterance is None
    assert reset_snapshot.finalized_utterances == ()
    assert first_new_event is not None
    assert first_new_event.session_id == SESSION_TWO
    assert first_new_event.sequence == 1
    assert first_new_event.revision == 1
    assert first_new_event.first_seen_ms == 0
