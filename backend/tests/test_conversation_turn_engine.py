import asyncio
from dataclasses import replace
from uuid import UUID

from app.services.conversation.engine import (
    ConversationTurnEngine,
    TurnFinalizationPolicy,
)
from app.services.conversation.models import (
    ContinuityQuality,
    TurnFinalizationReason,
)
from app.services.conversation.runtime import ConversationTurnRuntime
from app.services.stt.base import TranscriptResult
from app.services.transcript.models import (
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
)
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


def utterance(
    number: int,
    sequence: int,
    text: str,
    *,
    is_final: bool,
    revision: int = 1,
    observed_ms: int = 100,
    audio_source: AudioSource = AudioSource.MICROPHONE,
    speaker_role: SpeakerRole = SpeakerRole.LOCAL_USER,
) -> CanonicalUtterance:
    return CanonicalUtterance(
        session_id=SESSION_ID,
        utterance_id=UUID(f"10000000-0000-0000-0000-{number:012d}"),
        sequence=sequence,
        revision=revision,
        audio_source=audio_source,
        speaker_role=speaker_role,
        text=text,
        is_final=is_final,
        first_seen_ms=100,
        last_updated_ms=observed_ms,
        finalized_ms=observed_ms if is_final else None,
    )


def engine(window_ms: int = 250) -> ConversationTurnEngine:
    return ConversationTurnEngine(
        session_id=SESSION_ID,
        policy=TurnFinalizationPolicy(merge_window_ms=window_ms),
    )


def test_partial_corrections_keep_one_active_turn_and_stable_id() -> None:
    subject = engine()
    first = subject.observe(utterance(1, 1, "Can you", is_final=False))
    corrected = subject.observe(
        utterance(
            1,
            2,
            "Can you explain",
            is_final=False,
            revision=2,
            observed_ms=140,
        )
    )

    assert first.active_turn is not None
    assert corrected.active_turn is not None
    assert corrected.active_turn.turn_id == first.active_turn.turn_id
    assert corrected.active_turn.text == "Can you explain"
    assert corrected.active_turn.source_utterance_ids == (
        first.active_turn.source_utterance_ids[0],
    )
    assert corrected.active_turn.awaiting_finalization is False


def test_final_without_partial_waits_for_small_merge_window() -> None:
    subject = engine()
    update = subject.observe(
        utterance(1, 1, "Tell me about yourself.", is_final=True)
    )

    assert update.active_turn is not None
    assert update.active_turn.pending_deadline_ms == 350
    assert subject.finalize_due(now_ms=349) is None

    turn = subject.finalize_due(now_ms=350)
    assert turn is not None
    assert turn.text == "Tell me about yourself."
    assert turn.transcript_final_to_turn_ms == 250
    assert turn.finalization_reason is TurnFinalizationReason.MERGE_WINDOW_ELAPSED


def test_duplicate_and_stale_canonical_events_are_idempotent() -> None:
    subject = engine()
    final = utterance(1, 2, "What is Redis?", is_final=True, revision=2)
    first = subject.observe(final)
    duplicate = subject.observe(final)
    stale = subject.observe(replace(final, sequence=1, revision=1, is_final=False, finalized_ms=None))

    assert first.active_turn is not None
    assert duplicate.ignored is True
    assert stale.ignored is True
    turn = subject.finalize_due(now_ms=350)
    assert turn is not None
    assert len(subject.snapshot().finalized_turns) == 1


def test_nearby_final_segments_merge_with_full_provenance() -> None:
    subject = engine()
    subject.observe(utterance(1, 1, "Walk me through", is_final=True, observed_ms=100))
    update = subject.observe(
        utterance(2, 2, "your architecture.", is_final=True, observed_ms=220)
    )

    assert update.active_turn is not None
    assert update.active_turn.text == "Walk me through your architecture."
    assert update.active_turn.pending_deadline_ms == 470
    turn = subject.finalize_due(now_ms=470)
    assert turn is not None
    assert turn.source_transcript_sequences == (1, 2)
    assert len(turn.source_utterance_ids) == 2
    assert turn.transcript_final_to_turn_ms == 250


def test_elapsed_deadline_creates_distinct_monotonic_turns() -> None:
    subject = engine()
    subject.observe(utterance(1, 1, "First question?", is_final=True))
    first = subject.finalize_due(now_ms=350)
    subject.observe(utterance(2, 2, "Second question?", is_final=True, observed_ms=900))
    second = subject.finalize_due(now_ms=1_150)

    assert first is not None and second is not None
    assert (first.turn_sequence, second.turn_sequence) == (1, 2)
    assert first.turn_id != second.turn_id


def test_source_change_finalizes_previous_turn_immediately() -> None:
    subject = engine()
    subject.observe(utterance(1, 1, "Local request.", is_final=True))
    update = subject.observe(
        utterance(
            2,
            2,
            "Remote response.",
            is_final=True,
            observed_ms=180,
            audio_source=AudioSource.SYSTEM,
            speaker_role=SpeakerRole.REMOTE_SPEAKER,
        )
    )

    assert len(update.finalized_turns) == 1
    assert update.finalized_turns[0].finalization_reason is TurnFinalizationReason.SOURCE_CHANGED
    assert update.active_turn is not None
    assert update.active_turn.audio_source is AudioSource.SYSTEM
    assert update.active_turn.speaker_role is SpeakerRole.REMOTE_SPEAKER


def test_degraded_continuity_is_sticky_for_the_whole_turn() -> None:
    subject = engine()
    subject.observe(
        utterance(1, 1, "Suppose Redis", is_final=True),
        continuity_quality=ContinuityQuality.DEGRADED,
    )
    subject.observe(
        utterance(2, 2, "becomes unavailable.", is_final=True, observed_ms=150),
        continuity_quality=ContinuityQuality.NORMAL,
    )
    turn = subject.finalize_due(now_ms=400)

    assert turn is not None
    assert turn.continuity_quality is ContinuityQuality.DEGRADED


def test_stop_flushes_final_content_but_discards_partial_only_text() -> None:
    finalized = engine()
    finalized.observe(utterance(1, 1, "Give me an example.", is_final=True))
    turn = finalized.flush(
        now_ms=120,
        reason=TurnFinalizationReason.STOP_REQUESTED,
    )
    assert turn is not None
    assert turn.transcript_final_to_turn_ms == 20

    partial = engine()
    partial.observe(utterance(1, 1, "unfinished", is_final=False))
    assert partial.flush(
        now_ms=120,
        reason=TurnFinalizationReason.STOP_REQUESTED,
    ) is None
    assert partial.active_turn() is None


def test_cross_session_event_is_ignored_and_reset_clears_state() -> None:
    subject = engine()
    wrong_session = replace(
        utterance(1, 1, "Ignored", is_final=True),
        session_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    assert subject.observe(wrong_session).ignored is True
    subject.observe(utterance(1, 1, "Accepted", is_final=True))
    reset_session = UUID("00000000-0000-0000-0000-000000000003")
    snapshot = subject.reset(session_id=reset_session)
    assert snapshot.session_id == reset_session
    assert snapshot.turn_sequence == 0
    assert snapshot.active_turn is None


class ManualClock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class ManualSleeper:
    def __init__(self) -> None:
        self.futures: list[asyncio.Future[None]] = []

    async def __call__(self, _delay: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self.futures.append(future)
        await future

    def release_latest(self) -> None:
        self.futures[-1].set_result(None)


def test_runtime_deadline_and_pause_are_deterministic_and_leak_free() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        sleeper = ManualSleeper()
        turns = []
        runtime = ConversationTurnRuntime(
            engine=engine(),
            clock=clock,
            sleeper=sleeper,
            on_turn_finalized=lambda turn: _append(turns, turn),
        )

        update = await runtime.observe(
            utterance(1, 1, "How would you design this?", is_final=True),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        assert update.active_turn is not None
        assert update.active_turn.text == "How would you design this?"
        await asyncio.sleep(0)
        assert runtime.pending_task_count == 1

        clock.value = 350
        sleeper.release_latest()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(turns) == 1
        assert runtime.pending_task_count == 0

        await runtime.observe(
            utterance(2, 2, "Another question?", is_final=True, observed_ms=500),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        await asyncio.sleep(0)
        assert runtime.pending_task_count == 1
        await runtime.pause()
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_runtime_pause_preserves_pending_identity_and_resume_finishes_once() -> None:
    async def scenario() -> None:
        clock = ManualClock()
        first_sleeper = ManualSleeper()
        turns = []
        subject = engine()
        runtime = ConversationTurnRuntime(
            engine=subject,
            clock=clock,
            sleeper=first_sleeper,
            on_turn_finalized=lambda turn: _append(turns, turn),
        )
        await runtime.observe(
            utterance(1, 1, "What happens after reconnect?", is_final=True),
            continuity_quality=ContinuityQuality.NORMAL,
        )
        active = subject.active_turn()
        assert active is not None
        expected_id = active.turn_id
        await asyncio.sleep(0)
        await runtime.pause()
        assert runtime.pending_task_count == 0
        assert subject.active_turn() is not None

        clock.value = 500
        resumed_sleeper = ManualSleeper()
        resumed = ConversationTurnRuntime(
            engine=subject,
            clock=clock,
            sleeper=resumed_sleeper,
            on_turn_finalized=lambda turn: _append(turns, turn),
        )
        await resumed.resume()
        await asyncio.sleep(0)
        resumed_sleeper.release_latest()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert len(turns) == 1
        assert turns[0].turn_id == expected_id
        assert resumed.pending_task_count == 0

    asyncio.run(scenario())


def test_provider_generation_change_and_duplicate_final_do_not_duplicate_turn() -> None:
    async def scenario() -> None:
        session = TranscriptionSession(
            turn_policy=TurnFinalizationPolicy(merge_window_ms=0)
        )
        session.transition(SessionConnectionState.CONNECTED)
        turns = []
        runtime = ConversationTurnRuntime(
            engine=session.turn_engine,
            clock=session.elapsed_ms,
            on_turn_finalized=lambda turn: _append(turns, turn),
        )

        first = session.apply(TranscriptResult("Why Redis?", True, True))
        assert first is not None
        await runtime.observe(
            first,
            continuity_quality=session.conversation_continuity_quality,
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        session.transition(SessionConnectionState.RECONNECTING)
        session.transition(SessionConnectionState.CONNECTED)
        duplicate = session.apply(TranscriptResult("Why Redis?", True, True))
        assert duplicate is None

        second = session.apply(TranscriptResult("What next?", True, True))
        assert second is not None
        await runtime.observe(
            second,
            continuity_quality=session.conversation_continuity_quality,
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert session.provider_generation == 2
        assert [turn.text for turn in turns] == ["Why Redis?", "What next?"]
        assert [turn.turn_sequence for turn in turns] == [1, 2]
        await runtime.pause()

    asyncio.run(scenario())


async def _append(items: list, item) -> None:
    items.append(item)
