import asyncio
from uuid import UUID, uuid4

import pytest

from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.models import (
    AnswerFailureCategory,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
    AnswerSnapshot,
    AnswerState,
)
from app.services.answer.provider import AnswerProviderError
from app.services.answer.runtime import AnswerRuntime
from app.services.conversation.identity import (
    derive_assistance_detection_id,
    derive_turn_id,
)
from app.services.conversation.models import (
    AssistanceDecision,
    AssistanceKind,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


class ManualClock:
    def __init__(self, value: int = 1_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def _turn(sequence: int, text: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text or f"Question {sequence}?",
        started_ms=sequence * 100,
        last_updated_ms=sequence * 100 + 10,
        source_finalized_ms=sequence * 100 + 10,
        finalized_ms=sequence * 100 + 20,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=10,
    )


def _decision(turn: ConversationTurn) -> AssistanceDecision:
    return AssistanceDecision(
        detection_id=derive_assistance_detection_id(turn.turn_id),
        session_id=turn.session_id,
        source_turn_id=turn.turn_id,
        source_turn_sequence=turn.turn_sequence,
        should_assist=True,
        kind=AssistanceKind.QUESTION,
        detected_ms=turn.finalized_ms,
        turn_to_detection_ms=0,
    )


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=timeout)


def _runtime(
    provider: FakeAnswerProvider,
    clock: ManualClock,
    events: list[AnswerSnapshot],
    *,
    timeout_seconds: float = 1.0,
    sink_id: UUID | None = None,
) -> AnswerRuntime:
    runtime = AnswerRuntime(
        session_id=SESSION_ID,
        provider=provider,
        clock=clock,
        timeout_seconds=timeout_seconds,
    )
    runtime.attach_sink(sink_id or uuid4(), events.append)
    return runtime


def test_submit_returns_before_slow_provider_and_duplicate_is_not_called() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderCompleted(sequence=1),),
                    start_gate=gate,
                )
            ]
        )
        clock = ManualClock()
        events: list[AnswerSnapshot] = []
        runtime = _runtime(provider, clock, events)
        source = _turn(1)

        first = runtime.request_answer(
            _decision(source), source, recent_finalized_turns=(source,)
        )
        replay = runtime.request_answer(
            _decision(source), source, recent_finalized_turns=(source,)
        )

        assert first.created is True
        assert replay.created is False
        assert replay.snapshot.answer_id == first.snapshot.answer_id
        await _wait_until(lambda: len(provider.requests) == 1)
        assert runtime.pending_task_count == 1
        gate.set()
        await runtime.wait_idle()
        assert len(provider.requests) == 1
        assert runtime.snapshot().answers[0].state is AnswerState.COMPLETED

    asyncio.run(scenario())


def test_stream_updates_are_ordered_and_empty_completion_is_supported() -> None:
    async def scenario() -> None:
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="first "),
                        AnswerProviderTextDelta(sequence=2, text="second"),
                        AnswerProviderCompleted(sequence=3),
                    )
                ),
                FakeAnswerScript(steps=(AnswerProviderCompleted(sequence=1),)),
            ]
        )
        clock = ManualClock()
        events: list[AnswerSnapshot] = []
        runtime = _runtime(provider, clock, events)

        first = _turn(1)
        runtime.request_answer(_decision(first), first, recent_finalized_turns=(first,))
        await runtime.wait_idle()
        assert [event.state for event in events] == [
            AnswerState.STARTING,
            AnswerState.STREAMING,
            AnswerState.STREAMING,
            AnswerState.COMPLETED,
        ]
        assert events[-1].text == "first second"
        assert events[-1].stream_sequence == 2

        second = _turn(2)
        runtime.request_answer(
            _decision(second), second, recent_finalized_turns=(first, second)
        )
        await runtime.wait_idle()
        assert runtime.snapshot().answers[-1].state is AnswerState.COMPLETED
        assert runtime.snapshot().answers[-1].text == ""

    asyncio.run(scenario())


@pytest.mark.parametrize("after_partial", (False, True))
def test_provider_failure_is_terminal_before_or_after_partial_text(
    after_partial: bool,
) -> None:
    async def scenario() -> None:
        failure = AnswerProviderError(
            AnswerFailureCategory.PROVIDER_SERVER,
            "Answer provider is temporarily unavailable.",
            retryable=True,
        )
        steps = (
            (AnswerProviderTextDelta(sequence=1, text="partial"), failure)
            if after_partial
            else (failure,)
        )
        provider = FakeAnswerProvider([FakeAnswerScript(steps=steps)])
        clock = ManualClock()
        events: list[AnswerSnapshot] = []
        runtime = _runtime(provider, clock, events)
        source = _turn(1)
        runtime.request_answer(_decision(source), source, recent_finalized_turns=())
        await runtime.wait_idle()

        failed = runtime.snapshot().answers[0]
        assert failed.state is AnswerState.FAILED
        assert failed.text == ("partial" if after_partial else "")
        assert failed.failure is not None
        assert failed.failure.category is AnswerFailureCategory.PROVIDER_SERVER
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_timeout_closes_stream_and_does_not_leave_task() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderTextDelta(sequence=1, text="never"),),
                    step_gates=(gate,),
                )
            ]
        )
        runtime = _runtime(provider, ManualClock(), [], timeout_seconds=0.01)
        source = _turn(1)
        runtime.request_answer(_decision(source), source, recent_finalized_turns=())
        await runtime.wait_idle()

        answer = runtime.snapshot().answers[0]
        assert answer.state is AnswerState.FAILED
        assert answer.failure is not None
        assert answer.failure.category is AnswerFailureCategory.TIMEOUT
        assert provider.streams[0].closed
        assert provider.streams[0].cancelled
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_new_request_supersedes_stream_and_cancels_provider() -> None:
    async def scenario() -> None:
        blocked = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="A partial"),
                        AnswerProviderCompleted(sequence=2),
                    ),
                    step_gates=(None, blocked),
                ),
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="B answer"),
                        AnswerProviderCompleted(sequence=2),
                    )
                ),
            ]
        )
        runtime = _runtime(provider, ManualClock(), [])
        first = _turn(1)
        second = _turn(2)
        runtime.request_answer(_decision(first), first, recent_finalized_turns=())
        await _wait_until(
            lambda: runtime.snapshot().answers[0].state is AnswerState.STREAMING
        )

        runtime.request_answer(
            _decision(second), second, recent_finalized_turns=(first,)
        )
        await runtime.wait_idle()

        answers = runtime.snapshot().answers
        assert [answer.state for answer in answers] == [
            AnswerState.SUPERSEDED,
            AnswerState.COMPLETED,
        ]
        assert answers[0].text == "A partial"
        assert answers[1].text == "B answer"
        assert provider.streams[0].cancelled
        assert len(provider.requests) == 2

    asyncio.run(scenario())


def test_rapid_questions_leave_only_latest_generation_active() -> None:
    async def scenario() -> None:
        provider = FakeAnswerProvider(
            [FakeAnswerScript(steps=(AnswerProviderCompleted(sequence=1),))]
        )
        runtime = _runtime(provider, ManualClock(), [])
        turns = tuple(_turn(sequence) for sequence in (1, 2, 3))

        for turn in turns:
            runtime.request_answer(
                _decision(turn), turn, recent_finalized_turns=turns
            )
        await runtime.wait_idle()

        assert [answer.state for answer in runtime.snapshot().answers] == [
            AnswerState.SUPERSEDED,
            AnswerState.SUPERSEDED,
            AnswerState.COMPLETED,
        ]
        assert len(provider.requests) == 1
        assert provider.requests[0].answer_id == runtime.snapshot().answers[-1].answer_id

    asyncio.run(scenario())


def test_cancel_stop_and_reset_are_terminal_and_leak_free() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderCompleted(sequence=1),),
                    start_gate=gate,
                )
            ]
        )
        runtime = _runtime(provider, ManualClock(), [])
        source = _turn(1)
        runtime.request_answer(_decision(source), source, recent_finalized_turns=())
        await _wait_until(lambda: len(provider.requests) == 1)

        cancelled = runtime.cancel_active()
        assert cancelled is not None
        assert cancelled.state is AnswerState.CANCELLED
        await runtime.wait_idle()
        assert runtime.pending_task_count == 0

        new_session = UUID("00000000-0000-0000-0000-000000000099")
        runtime.reset(session_id=new_session)
        assert runtime.snapshot().session_id == new_session
        assert runtime.snapshot().answers == ()

    asyncio.run(scenario())


def test_disconnect_and_resume_replay_without_duplicate_provider_request() -> None:
    async def scenario() -> None:
        second_step = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(sequence=1, text="partial"),
                        AnswerProviderCompleted(sequence=2),
                    ),
                    step_gates=(None, second_step),
                )
            ]
        )
        clock = ManualClock()
        first_lease_events: list[AnswerSnapshot] = []
        first_sink_id = uuid4()
        runtime = _runtime(
            provider,
            clock,
            first_lease_events,
            sink_id=first_sink_id,
        )
        source = _turn(1)
        decision = _decision(source)
        runtime.request_answer(decision, source, recent_finalized_turns=())
        await _wait_until(
            lambda: runtime.snapshot().answers[0].state is AnswerState.STREAMING
        )

        assert runtime.detach_sink(first_sink_id)
        resumed_events: list[AnswerSnapshot] = []
        resumed_sink_id = uuid4()
        replay_snapshot = runtime.attach_sink(resumed_sink_id, resumed_events.append)
        resumed_events.extend(replay_snapshot.answers)
        assert resumed_events[-1].state is AnswerState.STREAMING
        assert not runtime.detach_sink(first_sink_id)

        replay = runtime.request_answer(decision, source, recent_finalized_turns=())
        assert replay.created is False
        second_step.set()
        await runtime.wait_idle()

        assert resumed_events[-1].state is AnswerState.COMPLETED
        assert len(provider.requests) == 1

    asyncio.run(scenario())


def test_disconnect_before_provider_start_continues_under_logical_session() -> None:
    async def scenario() -> None:
        start_gate = asyncio.Event()
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderCompleted(sequence=1),),
                    start_gate=start_gate,
                )
            ]
        )
        clock = ManualClock()
        first_events: list[AnswerSnapshot] = []
        first_sink_id = uuid4()
        runtime = _runtime(
            provider,
            clock,
            first_events,
            sink_id=first_sink_id,
        )
        source = _turn(1)
        decision = _decision(source)

        submission = runtime.request_answer(
            decision,
            source,
            recent_finalized_turns=(),
        )
        assert submission.snapshot.state is AnswerState.REQUESTED
        assert runtime.detach_sink(first_sink_id)

        resumed_events: list[AnswerSnapshot] = []
        resume_snapshot = runtime.attach_sink(uuid4(), resumed_events.append)
        assert resume_snapshot.answers[0].state is AnswerState.REQUESTED

        await _wait_until(lambda: len(provider.requests) == 1)
        start_gate.set()
        await runtime.wait_idle()

        assert resumed_events[-1].state is AnswerState.COMPLETED
        assert len(provider.requests) == 1
        assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_malformed_stream_fails_without_raising_to_caller() -> None:
    async def scenario() -> None:
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(AnswerProviderTextDelta(sequence=2, text="bad"),)
                )
            ]
        )
        runtime = _runtime(provider, ManualClock(), [])
        source = _turn(1)
        runtime.request_answer(_decision(source), source, recent_finalized_turns=())
        await runtime.wait_idle()
        answer = runtime.snapshot().answers[0]
        assert answer.state is AnswerState.FAILED
        assert answer.failure is not None
        assert answer.failure.category is AnswerFailureCategory.MALFORMED_STREAM

    asyncio.run(scenario())


def test_cross_session_detection_is_rejected_before_provider_call() -> None:
    provider = FakeAnswerProvider([])
    runtime = AnswerRuntime(
        session_id=UUID("00000000-0000-0000-0000-000000000099"),
        provider=provider,
        clock=ManualClock(),
    )
    source = _turn(1)
    with pytest.raises(ValueError, match="another session"):
        runtime.request_answer(_decision(source), source, recent_finalized_turns=())
    assert provider.requests == []


def test_normal_answer_logs_do_not_contain_question_or_answer_content(caplog) -> None:
    async def scenario() -> None:
        provider = FakeAnswerProvider(
            [
                FakeAnswerScript(
                    steps=(
                        AnswerProviderTextDelta(
                            sequence=1,
                            text="private generated answer body",
                        ),
                        AnswerProviderCompleted(sequence=2),
                    )
                )
            ]
        )
        runtime = _runtime(provider, ManualClock(), [])
        source = _turn(1, "private spoken question body?")
        runtime.request_answer(
            _decision(source),
            source,
            recent_finalized_turns=(),
        )
        await runtime.wait_idle()

    with caplog.at_level("INFO", logger="app.services.answer.runtime"):
        asyncio.run(scenario())
    rendered = caplog.text
    assert "private spoken question body" not in rendered
    assert "private generated answer body" not in rendered
    assert "answer_request_to_first_text_ms" in rendered
