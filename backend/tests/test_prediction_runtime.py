import asyncio
from dataclasses import dataclass, replace
import time
from collections.abc import Callable
from uuid import UUID

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import ActiveConversationTurn, ContinuityQuality
from app.services.conversation.models import ConversationTurn, TurnFinalizationReason
from app.services.memory import ConversationMemory, MemorySnapshot
from app.services.prediction import (
    DeterministicPredictionContextPlanner,
    DeterministicPredictionTriggerPolicy,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionFailureCategory,
    PredictionInvalidationReason,
    PredictionProviderError,
    PredictionProviderResult,
    PredictionReadiness,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionContextPlanner,
    PredictionState,
    PredictionTriggerPolicy,
    PredictionTriggerPolicyLimits,
    PredictionTriggerReason,
    PredictionUsage,
    derive_prediction_id,
)
from app.services.prediction.runtime import PredictionAttemptInput
from app.services.transcript.models import (
    AudioSource,
    CanonicalUtterance,
    SpeakerRole,
)


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_SESSION_ID = UUID("00000000-0000-0000-0000-000000000002")


class ManualClock:
    def __init__(self, value: int = 200) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


@dataclass(slots=True)
class ExecutorScript:
    result: PredictionProviderResult | None = None
    error: BaseException | None = None
    gate: asyncio.Event | None = None
    suppress_cancellation: bool = False


class ControlledExecutor:
    def __init__(self, scripts: list[ExecutorScript]) -> None:
        self.scripts = scripts
        self.attempts: list[PredictionAttemptInput] = []
        self.active_count = 0
        self.max_active_count = 0

    async def execute(
        self,
        attempt: PredictionAttemptInput,
    ) -> PredictionProviderResult:
        index = len(self.attempts)
        self.attempts.append(attempt)
        script = self.scripts[index]
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            if script.gate is not None:
                try:
                    await script.gate.wait()
                except asyncio.CancelledError:
                    if not script.suppress_cancellation:
                        raise
            if script.error is not None:
                raise script.error
            if script.result is None:
                raise AssertionError("controlled prediction script has no result")
            return script.result
        finally:
            self.active_count -= 1


def candidate(text: str = "Why did you choose Redis?") -> PredictionCandidate:
    return PredictionCandidate(
        kind=PredictionCandidateKind.QUESTION,
        text=text,
        anchor_terms=("redis",),
    )


def provider_result(text: str = "Why did you choose Redis?") -> PredictionProviderResult:
    return PredictionProviderResult(
        candidates=(candidate(text),),
        usage=PredictionUsage(input_tokens=20, output_tokens=8, total_tokens=28),
        finish_reason="stop",
    )


def active_turn(
    text: str = "You mentioned Redis in your architecture",
    *,
    turn_sequence: int = 3,
    utterance_number: int = 1,
    transcript_sequence: int = 7,
    awaiting_finalization: bool = False,
    audio_source: AudioSource = AudioSource.MICROPHONE,
    speaker_role: SpeakerRole = SpeakerRole.LOCAL_USER,
    continuity_quality: ContinuityQuality = ContinuityQuality.NORMAL,
) -> ActiveConversationTurn:
    return ActiveConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, turn_sequence),
        turn_sequence=turn_sequence,
        source_utterance_ids=(UUID(int=utterance_number),),
        source_transcript_sequences=(transcript_sequence,),
        audio_source=audio_source,
        speaker_role=speaker_role,
        text=text,
        started_ms=100,
        last_updated_ms=180,
        continuity_quality=continuity_quality,
        awaiting_finalization=awaiting_finalization,
        pending_deadline_ms=430 if awaiting_finalization else None,
    )


def utterance(
    text: str = "You mentioned Redis in your architecture",
    *,
    utterance_number: int = 1,
    transcript_sequence: int = 7,
    revision: int = 1,
    is_final: bool = False,
    audio_source: AudioSource = AudioSource.MICROPHONE,
    speaker_role: SpeakerRole = SpeakerRole.LOCAL_USER,
) -> CanonicalUtterance:
    return CanonicalUtterance(
        session_id=SESSION_ID,
        utterance_id=UUID(int=utterance_number),
        sequence=transcript_sequence,
        revision=revision,
        audio_source=audio_source,
        speaker_role=speaker_role,
        text=text,
        is_final=is_final,
        first_seen_ms=100,
        last_updated_ms=180,
        finalized_ms=180 if is_final else None,
    )


def runtime(
    executor: ControlledExecutor,
    *,
    clock: Callable[[], int] | None = None,
    coalesce_seconds: float = 0,
    timeout_seconds: float = 1,
    turn_limit: int = 3,
    session_limit: int = 8,
    cancelled_attempt_cooldown_seconds: float = 0,
    max_compatible_extension_chars: int = 0,
    trigger_policy: PredictionTriggerPolicy | None = None,
    context_planner: PredictionContextPlanner | None = None,
    memory_snapshot_supplier: Callable[[], MemorySnapshot | None] | None = None,
) -> PredictionRuntime:
    return PredictionRuntime(
        session_id=SESSION_ID,
        executor=executor,
        clock=clock or ManualClock(),
        limits=PredictionRuntimeLimits(
            coalesce_seconds=coalesce_seconds,
            provider_timeout_seconds=timeout_seconds,
            max_attempts_per_turn=turn_limit,
            max_calls_per_session=session_limit,
            cancelled_attempt_cooldown_seconds=cancelled_attempt_cooldown_seconds,
            max_compatible_extension_chars=max_compatible_extension_chars,
        ),
        trigger_policy=(
            trigger_policy
            or DeterministicPredictionTriggerPolicy(
                limits=PredictionTriggerPolicyLimits(min_call_interval_ms=0)
            )
        ),
        context_planner=context_planner,
        memory_snapshot_supplier=memory_snapshot_supplier,
    )


def test_running_attempt_survives_only_a_conservative_append_only_preface() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        executor = ControlledExecutor([ExecutorScript(provider_result(), gate=gate)])
        subject = runtime(
            executor,
            turn_limit=1,
            max_compatible_extension_chars=96,
        )
        basis_text = "You mentioned Redis in your architecture"
        first = subject.observe_nowait(
            active_turn(basis_text),
            utterance(basis_text),
            memory_revision=2,
        )
        assert first.scheduled is True
        await wait_for_attempts(executor, 1)

        extended_text = f"{basis_text} and I am interested in the tradeoffs"
        compatible = subject.observe_nowait(
            active_turn(extended_text),
            utterance(extended_text, revision=2),
            memory_revision=2,
        )
        assert compatible.materially_changed is False
        assert compatible.scheduled is False
        assert compatible.trigger_reason is PredictionTriggerReason.COMPATIBLE_EXTENSION
        assert compatible.snapshot.current is not None
        assert compatible.snapshot.current.input_revision == 1
        assert compatible.snapshot.current.state is PredictionState.RUNNING
        assert subject.turn_compatible_extension_count == 1

        duplicate = subject.observe_nowait(
            active_turn(extended_text),
            utterance(extended_text, revision=2),
            memory_revision=2,
        )
        assert duplicate.materially_changed is False
        assert duplicate.trigger_reason is PredictionTriggerReason.UNCHANGED
        assert duplicate.snapshot.current is not None
        assert duplicate.snapshot.current.input_revision == 1
        assert subject.turn_compatible_extension_count == 1

        gate.set()
        await subject.wait_idle()
        ready = subject.snapshot().current
        assert ready is not None
        assert ready.state is PredictionState.READY
        assert ready.input_revision == 1
        assert len(executor.attempts) == 1
        assert executor.attempts[0].active_turn.text == basis_text

        ready_extension = f"{extended_text} particularly"
        still_ready = subject.observe_nowait(
            active_turn(ready_extension),
            utterance(ready_extension, revision=3),
            memory_revision=2,
        )
        assert still_ready.materially_changed is False
        assert still_ready.snapshot.current is not None
        assert still_ready.snapshot.current.state is PredictionState.READY
        assert still_ready.snapshot.current.candidates == ready.candidates

        question_text = f"{ready_extension} what happens if Redis fails"
        changed = subject.observe_nowait(
            active_turn(question_text),
            utterance(question_text, revision=4),
            memory_revision=2,
        )
        assert changed.materially_changed is True
        assert changed.snapshot.current is not None
        assert changed.snapshot.current.input_revision == 2
        assert changed.snapshot.current.candidates == ()
        assert changed.snapshot.current.state is PredictionState.INVALIDATED

        subject.shutdown_nowait()
        await subject.wait_idle()

    asyncio.run(scenario())


async def wait_for_attempts(executor: ControlledExecutor, count: int) -> None:
    for _ in range(100):
        if len(executor.attempts) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"prediction attempt count did not reach {count}")


def test_observation_is_nonblocking_and_provider_final_same_text_is_a_noop() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        executor = ControlledExecutor([ExecutorScript(provider_result(), gate=gate)])
        subject = runtime(executor)

        first = subject.observe_nowait(active_turn(), utterance(), memory_revision=2)
        assert first.materially_changed is True
        assert first.scheduled is True
        assert first.snapshot.state is PredictionState.SCHEDULED
        await wait_for_attempts(executor, 1)

        finalized_active = replace(
            active_turn(awaiting_finalization=True),
            source_transcript_sequences=(8,),
        )
        repeated = subject.observe_nowait(
            finalized_active,
            utterance(
                transcript_sequence=8,
                revision=2,
                is_final=True,
            ),
            memory_revision=2,
        )
        assert repeated.materially_changed is False
        assert repeated.scheduled is False
        assert repeated.snapshot.current is not None
        assert repeated.snapshot.current.input_revision == 1
        assert repeated.snapshot.current.active_turn_awaiting_finalization is True
        assert len(executor.attempts) == 1

        gate.set()
        await subject.wait_idle()
        ready = subject.snapshot()
        assert ready.state is PredictionState.READY
        assert ready.current is not None
        assert ready.current.active_turn_awaiting_finalization is True
        assert ready.current.readiness is PredictionReadiness.TENTATIVE
        assert ready.provider_attempt_count == 1
        assert subject.pending_task_count == 0

    asyncio.run(scenario())


def test_rapid_correction_cancels_old_work_and_discards_its_stale_result() -> None:
    async def scenario() -> None:
        first_gate = asyncio.Event()
        executor = ControlledExecutor(
            [
                ExecutorScript(
                    provider_result("Why Redis?"),
                    gate=first_gate,
                    suppress_cancellation=True,
                ),
                ExecutorScript(provider_result("How is cache failure handled?")),
            ]
        )
        subject = runtime(executor)
        snapshots = []
        subject.attach_sink(UUID(int=99), snapshots.append)

        first = subject.observe_nowait(active_turn(), utterance(), memory_revision=2)
        await wait_for_attempts(executor, 1)
        corrected_active = active_turn("You mentioned cache failure handling")
        corrected_utterance = utterance(
            "You mentioned cache failure handling",
            revision=2,
        )
        corrected = subject.observe_nowait(
            corrected_active,
            corrected_utterance,
            memory_revision=2,
        )
        await subject.wait_idle()

        final = subject.snapshot()
        assert first.snapshot.current is not None
        assert corrected.snapshot.current is not None
        assert first.snapshot.current.prediction_id == corrected.snapshot.current.prediction_id
        assert corrected.snapshot.current.input_revision == 2
        assert final.current is not None
        assert final.current.input_revision == 2
        assert final.current.candidates[0].text == "How is cache failure handled?"
        assert final.provider_attempt_count == 2
        assert final.cancelled_call_count == 1
        assert final.stale_discard_count == 1
        assert executor.max_active_count == 1
        revisions = [
            item.snapshot_revision
            for item in snapshots
            if item.prediction_id == final.current.prediction_id
        ]
        assert revisions == sorted(set(revisions))

    asyncio.run(scenario())


def test_coalescing_keeps_only_the_latest_material_input() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor([ExecutorScript(provider_result("Why DynamoDB?"))])
        subject = runtime(executor, coalesce_seconds=0.02)

        subject.observe_nowait(active_turn(), utterance(), memory_revision=1)
        corrected = active_turn("You mentioned DynamoDB instead")
        subject.observe_nowait(
            corrected,
            utterance("You mentioned DynamoDB instead", revision=2),
            memory_revision=1,
        )
        await subject.wait_idle()

        assert len(executor.attempts) == 1
        assert executor.attempts[0].active_turn.text == corrected.text
        assert executor.attempts[0].input_revision == 2
        assert subject.snapshot().provider_attempt_count == 1

    asyncio.run(scenario())


def test_new_turn_gets_new_identity_and_resets_input_revision() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor(
            [ExecutorScript(provider_result()), ExecutorScript(provider_result("Why Kafka?"))]
        )
        subject = runtime(executor)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()
        first = subject.snapshot().current
        assert first is not None

        next_active = active_turn(
            "You mentioned Kafka",
            turn_sequence=4,
            utterance_number=2,
            transcript_sequence=8,
        )
        subject.observe_nowait(
            next_active,
            utterance(
                "You mentioned Kafka",
                utterance_number=2,
                transcript_sequence=8,
            ),
            memory_revision=1,
        )
        await subject.wait_idle()
        second = subject.snapshot().current

        assert second is not None
        assert second.prediction_id != first.prediction_id
        assert second.prediction_id == derive_prediction_id(SESSION_ID, next_active.turn_id)
        assert second.input_revision == 1
        assert second.attempt == 1
        assert subject.snapshot().provider_attempt_count == 2

    asyncio.run(scenario())


def test_material_invalidation_reasons_are_emitted_before_new_work() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor(
            [ExecutorScript(provider_result()), ExecutorScript(provider_result())]
        )
        subject = runtime(executor)
        events = []
        subject.attach_sink(UUID(int=88), events.append)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=2)
        await subject.wait_idle()

        subject.observe_nowait(active_turn(), utterance(), memory_revision=3)
        await subject.wait_idle()

        invalidated = [event for event in events if event.state is PredictionState.INVALIDATED]
        assert invalidated[-1].invalidation_reason is (
            PredictionInvalidationReason.MEMORY_REVISION_CHANGED
        )
        assert subject.snapshot().current is not None
        assert subject.snapshot().current.memory_revision == 3

    asyncio.run(scenario())


def test_provenance_and_source_changes_have_explicit_invalidation_reasons() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor(
            [
                ExecutorScript(provider_result()),
                ExecutorScript(provider_result()),
                ExecutorScript(provider_result()),
            ]
        )
        subject = runtime(executor)
        events = []
        subject.attach_sink(UUID(int=87), events.append)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()

        changed_provenance = replace(
            active_turn("You mentioned Redis in your architecture and caching"),
            source_utterance_ids=(UUID(int=1), UUID(int=2)),
            source_transcript_sequences=(7, 8),
        )
        subject.observe_nowait(
            changed_provenance,
            utterance(
                "and caching",
                utterance_number=2,
                transcript_sequence=8,
            ),
            memory_revision=0,
        )
        await subject.wait_idle()

        changed_source = replace(
            changed_provenance,
            audio_source=AudioSource.SYSTEM,
            speaker_role=SpeakerRole.REMOTE_SPEAKER,
            text="You mentioned Redis from the remote speaker",
        )
        subject.observe_nowait(
            changed_source,
            utterance(
                "remote speaker",
                utterance_number=2,
                transcript_sequence=8,
                revision=2,
                audio_source=AudioSource.SYSTEM,
                speaker_role=SpeakerRole.REMOTE_SPEAKER,
            ),
            memory_revision=0,
        )
        await subject.wait_idle()

        reasons = [
            event.invalidation_reason
            for event in events
            if event.state is PredictionState.INVALIDATED
        ]
        assert PredictionInvalidationReason.ACTIVE_PROVENANCE_CHANGED in reasons
        assert PredictionInvalidationReason.SOURCE_OR_SPEAKER_CHANGED in reasons

    asyncio.run(scenario())


def test_degraded_continuity_invalidates_without_calling_executor() -> None:
    executor = ControlledExecutor([])
    subject = runtime(executor)
    degraded = active_turn(continuity_quality=ContinuityQuality.DEGRADED)

    submission = subject.observe_nowait(degraded, utterance(), memory_revision=0)

    assert submission.scheduled is False
    assert submission.snapshot.state is PredictionState.INVALIDATED
    assert submission.snapshot.current is not None
    assert submission.snapshot.current.invalidation_reason is (
        PredictionInvalidationReason.CONTINUITY_DEGRADED
    )
    assert executor.attempts == []


def test_hard_turn_and_session_call_ceilings_do_not_start_extra_work() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor([ExecutorScript(provider_result())])
        subject = runtime(executor, turn_limit=1, session_limit=1)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()

        correction = active_turn("You mentioned Redis durability")
        blocked = subject.observe_nowait(
            correction,
            utterance("You mentioned Redis durability", revision=2),
            memory_revision=0,
        )
        assert blocked.scheduled is False
        assert blocked.snapshot.current is not None
        assert blocked.snapshot.current.invalidation_reason is (
            PredictionInvalidationReason.SESSION_CALL_LIMIT
        )
        assert len(executor.attempts) == 1

        turn_executor = ControlledExecutor([ExecutorScript(provider_result())])
        turn_bounded = runtime(turn_executor, turn_limit=1, session_limit=4)
        turn_bounded.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await turn_bounded.wait_idle()
        turn_blocked = turn_bounded.observe_nowait(
            correction,
            utterance("You mentioned Redis durability", revision=2),
            memory_revision=0,
        )
        assert turn_blocked.scheduled is False
        assert turn_blocked.snapshot.current is not None
        assert turn_blocked.snapshot.current.invalidation_reason is (
            PredictionInvalidationReason.TURN_ATTEMPT_LIMIT
        )
        assert len(turn_executor.attempts) == 1

    asyncio.run(scenario())


def test_stable_readiness_means_repeated_candidate_plus_finalization_wait() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor(
            [ExecutorScript(provider_result()), ExecutorScript(provider_result())]
        )
        subject = runtime(executor)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()

        evolved = active_turn(
            "You mentioned Redis in your architecture, so why",
            awaiting_finalization=True,
        )
        subject.observe_nowait(
            evolved,
            utterance(
                "You mentioned Redis in your architecture, so why",
                revision=2,
                is_final=True,
            ),
            memory_revision=0,
        )
        await subject.wait_idle()

        ready = subject.snapshot().current
        assert ready is not None
        assert ready.candidate_consistent_revision_count == 2
        assert ready.readiness is PredictionReadiness.STABLE

    asyncio.run(scenario())


def test_timeout_and_provider_error_are_isolated_as_safe_failures() -> None:
    async def scenario() -> None:
        never = asyncio.Event()
        timeout_executor = ControlledExecutor(
            [ExecutorScript(provider_result(), gate=never)]
        )
        timed = runtime(timeout_executor, timeout_seconds=0.01)
        timed.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await timed.wait_idle()
        timed_snapshot = timed.snapshot()
        assert timed_snapshot.state is PredictionState.FAILED
        assert timed_snapshot.current is not None
        assert timed_snapshot.current.failure is not None
        assert timed_snapshot.current.failure.category is PredictionFailureCategory.TIMEOUT
        assert timed.pending_task_count == 0

        provider_error = PredictionProviderError(
            PredictionFailureCategory.AUTHENTICATION,
            "Prediction provider is not authorized.",
            retryable=False,
        )
        error_executor = ControlledExecutor([ExecutorScript(error=provider_error)])
        failed = runtime(error_executor)
        failed.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await failed.wait_idle()
        failed_snapshot = failed.snapshot()
        assert failed_snapshot.state is PredictionState.FAILED
        assert failed_snapshot.current is not None
        assert failed_snapshot.current.failure is not None
        assert failed_snapshot.current.failure.category is (
            PredictionFailureCategory.AUTHENTICATION
        )
        assert failed.pending_task_count == 0

        events = []
        failed.attach_sink(UUID(int=77), events.append)
        failed.shutdown_nowait(
            reason=PredictionInvalidationReason.STOP_REQUESTED
        )
        assert any(
            event.state is PredictionState.INVALIDATED
            and event.invalidation_reason
            is PredictionInvalidationReason.STOP_REQUESTED
            and event.failure is None
            for event in events
        )

    asyncio.run(scenario())


def test_disconnect_cancels_and_clears_ephemeral_state_until_new_input_after_attach() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        executor = ControlledExecutor(
            [ExecutorScript(provider_result(), gate=gate), ExecutorScript(provider_result())]
        )
        subject = runtime(executor)
        sink_id = UUID(int=76)
        subject.attach_sink(sink_id, lambda _snapshot: None)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await wait_for_attempts(executor, 1)

        await subject.disconnect()
        assert subject.snapshot().state is PredictionState.IDLE
        assert subject.pending_task_count == 0
        assert subject.snapshot().cancelled_call_count == 1
        assert subject.detach_sink(sink_id) is False

        subject.attach_browser()
        assert len(executor.attempts) == 1
        await asyncio.sleep(0)
        assert len(executor.attempts) == 1

        subject.observe_nowait(active_turn(), utterance(revision=2), memory_revision=0)
        await subject.wait_idle()
        assert len(executor.attempts) == 2
        assert subject.snapshot().state is PredictionState.READY

    asyncio.run(scenario())


def test_turn_finalization_reset_and_shutdown_leave_no_async_tasks() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        executor = ControlledExecutor(
            [
                ExecutorScript(provider_result(), gate=gate),
                ExecutorScript(provider_result(), gate=asyncio.Event()),
            ]
        )
        subject = runtime(executor)
        current_active = active_turn()
        subject.observe_nowait(current_active, utterance(), memory_revision=0)
        await wait_for_attempts(executor, 1)
        invalidated = subject.invalidate_turn_nowait(
            current_active.turn_id,
            reason=PredictionInvalidationReason.TURN_FINALIZED,
            at_ms=0,
        )
        await subject.wait_idle()
        assert invalidated is not None
        assert invalidated.terminal_ms == invalidated.input_observed_ms
        assert subject.pending_task_count == 0

        subject.reset(session_id=OTHER_SESSION_ID)
        assert subject.session_id == OTHER_SESSION_ID
        assert subject.snapshot().state is PredictionState.IDLE
        assert subject.snapshot().provider_attempt_count == 0

        subject.shutdown_nowait(
            reason=PredictionInvalidationReason.BACKEND_SHUTDOWN
        )
        await subject.wait_idle()
        assert subject.pending_task_count == 0

    asyncio.run(scenario())


def test_reset_can_be_reused_immediately_while_old_worker_unwinds() -> None:
    async def scenario() -> None:
        old_gate = asyncio.Event()
        executor = ControlledExecutor(
            [
                ExecutorScript(provider_result(), gate=old_gate),
                ExecutorScript(provider_result("Why Kafka?")),
            ]
        )
        subject = runtime(executor)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await wait_for_attempts(executor, 1)

        subject.reset(session_id=OTHER_SESSION_ID)
        other_active = replace(
            active_turn("You mentioned Kafka"),
            session_id=OTHER_SESSION_ID,
            turn_id=derive_turn_id(OTHER_SESSION_ID, 3),
        )
        other_utterance = replace(
            utterance("You mentioned Kafka", revision=2),
            session_id=OTHER_SESSION_ID,
        )
        subject.observe_nowait(other_active, other_utterance, memory_revision=0)
        await subject.wait_idle()

        ready = subject.snapshot()
        assert ready.session_id == OTHER_SESSION_ID
        assert ready.state is PredictionState.READY
        assert ready.current is not None
        assert ready.current.candidates[0].text == "Why Kafka?"
        assert ready.provider_attempt_count == 1
        assert subject.pending_task_count == 0
        assert executor.max_active_count == 1

    asyncio.run(scenario())


def test_cross_session_and_mismatched_provenance_are_rejected_locally() -> None:
    executor = ControlledExecutor([])
    subject = runtime(executor)

    wrong_session = replace(active_turn(), session_id=OTHER_SESSION_ID)
    try:
        subject.observe_nowait(wrong_session, utterance(), memory_revision=0)
    except ValueError as exc:
        assert "another prediction session" in str(exc)
    else:
        raise AssertionError("cross-session prediction input was accepted")

    wrong_sequence = replace(utterance(), sequence=8)
    try:
        subject.observe_nowait(active_turn(), wrong_sequence, memory_revision=0)
    except ValueError as exc:
        assert "sequence" in str(exc)
    else:
        raise AssertionError("mismatched prediction provenance was accepted")


def test_normal_logs_exclude_active_and_candidate_bodies(caplog) -> None:
    async def scenario() -> None:
        active_secret = "PRIVATE_ACTIVE_SENTENCE_4b3d"
        candidate_secret = "PRIVATE_CANDIDATE_SENTENCE_8a2f"
        executor = ControlledExecutor(
            [ExecutorScript(provider_result(candidate_secret))]
        )
        subject = runtime(executor)

        subject.observe_nowait(
            active_turn(active_secret),
            utterance(active_secret),
            memory_revision=0,
        )
        await subject.wait_idle()

        assert active_secret not in caplog.text
        assert candidate_secret not in caplog.text

    asyncio.run(scenario())


def test_event_sink_failure_is_isolated_without_logging_exception_body(caplog) -> None:
    async def scenario() -> None:
        private_exception_body = "PRIVATE_SINK_BODY_2d91"
        executor = ControlledExecutor([ExecutorScript(provider_result())])
        subject = runtime(executor)

        def broken_sink(_snapshot) -> None:
            raise RuntimeError(private_exception_body)

        subject.attach_sink(UUID(int=98), broken_sink)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()

        assert subject.snapshot().state is PredictionState.READY
        assert len(executor.attempts) == 1
        assert private_exception_body not in caplog.text
        assert "exception_type=RuntimeError" in caplog.text

    asyncio.run(scenario())


def memory_turn(sequence: int, text: str) -> ConversationTurn:
    base = sequence * 100
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence + 100),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=base,
        last_updated_ms=base + 10,
        source_finalized_ms=base + 10,
        finalized_ms=base + 20,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=10,
    )


def test_trigger_suppression_happens_before_attempt_or_context_planning() -> None:
    class CountingPlanner:
        calls = 0

        def plan(self, snapshot, active_turn, *, input_revision):
            self.calls += 1
            return DeterministicPredictionContextPlanner().plan(
                snapshot,
                active_turn,
                input_revision=input_revision,
            )

    executor = ControlledExecutor([])
    planner = CountingPlanner()
    subject = runtime(executor, context_planner=planner)

    short = subject.observe_nowait(
        active_turn("okay"),
        utterance("okay"),
        memory_revision=0,
    )

    assert short.scheduled is False
    assert short.trigger_reason is PredictionTriggerReason.BACKCHANNEL
    assert executor.attempts == []
    assert planner.calls == 0
    assert subject.snapshot().provider_attempt_count == 0
    assert subject.snapshot().suppressed_observation_count == 1


def test_weak_correction_invalidates_ready_prediction_without_replacement() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor([ExecutorScript(provider_result())])
        subject = runtime(executor)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()
        assert subject.snapshot().state is PredictionState.READY

        suppressed = subject.observe_nowait(
            active_turn("regarding that"),
            utterance("regarding that", revision=2),
            memory_revision=0,
        )

        assert suppressed.scheduled is False
        assert suppressed.trigger_reason is PredictionTriggerReason.TOO_SHORT
        assert subject.snapshot().state is PredictionState.INVALIDATED
        assert subject.snapshot().current is not None
        assert subject.snapshot().current.candidates == ()
        assert len(executor.attempts) == 1

    asyncio.run(scenario())


def test_context_is_planned_in_worker_and_carries_bounded_memory() -> None:
    async def scenario() -> None:
        memory = ConversationMemory(session_id=SESSION_ID)
        memory.observe(memory_turn(1, "Redis is used for the session cache."))
        memory.observe(memory_turn(2, "The service is deployed in three zones."))
        snapshot = memory.snapshot()

        class CountingPlanner:
            calls = 0

            def plan(self, memory_snapshot, current_active, *, input_revision):
                self.calls += 1
                return DeterministicPredictionContextPlanner().plan(
                    memory_snapshot,
                    current_active,
                    input_revision=input_revision,
                )

        planner = CountingPlanner()
        executor = ControlledExecutor([ExecutorScript(provider_result())])
        subject = runtime(
            executor,
            context_planner=planner,
            memory_snapshot_supplier=memory.snapshot,
        )
        current = active_turn(
            "Coming back to Redis, what happens if the cache fails?",
            turn_sequence=3,
        )
        source = utterance()

        submission = subject.observe_nowait(
            current,
            source,
            memory_revision=snapshot.memory_revision,
        )
        assert submission.scheduled is True
        assert planner.calls == 0

        await subject.wait_idle()

        assert planner.calls == 1
        assert len(executor.attempts) == 1
        context = executor.attempts[0].context
        assert context.memory_revision == snapshot.memory_revision
        assert context.active_turn.text == current.text
        assert [turn.turn_sequence for turn in context.recent_memory] == [1, 2]
        ready = subject.snapshot().current
        assert ready is not None
        assert ready.context_chars == context.total_text_chars

    asyncio.run(scenario())


def test_memory_revision_race_invalidates_before_provider_call() -> None:
    async def scenario() -> None:
        memory = ConversationMemory(session_id=SESSION_ID)
        executor = ControlledExecutor([])
        subject = runtime(
            executor,
            coalesce_seconds=0.02,
            memory_snapshot_supplier=memory.snapshot,
        )
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        memory.observe(memory_turn(1, "Canonical memory changed after observation."))

        await subject.wait_idle()

        snapshot = subject.snapshot()
        assert executor.attempts == []
        assert snapshot.provider_attempt_count == 0
        assert snapshot.state is PredictionState.INVALIDATED
        assert snapshot.current is not None
        assert snapshot.current.invalidation_reason is (
            PredictionInvalidationReason.MEMORY_REVISION_CHANGED
        )

    asyncio.run(scenario())


def test_context_supplier_and_planner_failures_are_isolated_before_provider() -> None:
    async def scenario() -> None:
        def broken_supplier():
            raise RuntimeError("private memory failure")

        first_executor = ControlledExecutor([])
        unavailable = runtime(
            first_executor,
            memory_snapshot_supplier=broken_supplier,
        )
        unavailable.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await unavailable.wait_idle()
        assert first_executor.attempts == []
        assert unavailable.snapshot().current is not None
        assert unavailable.snapshot().current.invalidation_reason is (
            PredictionInvalidationReason.CONTEXT_UNAVAILABLE
        )

        class BrokenPlanner:
            def plan(self, snapshot, active_turn, *, input_revision):
                raise ValueError("private active text")

        memory = ConversationMemory(session_id=SESSION_ID)
        second_executor = ControlledExecutor([])
        invalid = runtime(
            second_executor,
            context_planner=BrokenPlanner(),
            memory_snapshot_supplier=memory.snapshot,
        )
        invalid.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await invalid.wait_idle()
        assert second_executor.attempts == []
        assert invalid.snapshot().current is not None
        assert invalid.snapshot().current.invalidation_reason is (
            PredictionInvalidationReason.CONTEXT_UNAVAILABLE
        )

        class MismatchedPlanner:
            def plan(self, snapshot, active, *, input_revision):
                context = DeterministicPredictionContextPlanner().plan(
                    snapshot,
                    active,
                    input_revision=input_revision,
                )
                mismatched_active = replace(
                    context.active_turn,
                    text="X" * len(context.active_turn.text),
                )
                return replace(context, active_turn=mismatched_active)

        third_executor = ControlledExecutor([])
        mismatched = runtime(
            third_executor,
            context_planner=MismatchedPlanner(),
            memory_snapshot_supplier=memory.snapshot,
        )
        mismatched.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await mismatched.wait_idle()
        assert third_executor.attempts == []
        assert mismatched.snapshot().provider_attempt_count == 0
        assert mismatched.snapshot().current is not None
        assert mismatched.snapshot().current.invalidation_reason is (
            PredictionInvalidationReason.CONTEXT_UNAVAILABLE
        )

    asyncio.run(scenario())


def test_minimum_call_interval_delays_new_work_without_queuing_attempts() -> None:
    async def scenario() -> None:
        now = lambda: int(time.monotonic() * 1_000)
        executor = ControlledExecutor(
            [ExecutorScript(provider_result()), ExecutorScript(provider_result())]
        )
        policy = DeterministicPredictionTriggerPolicy(
            limits=PredictionTriggerPolicyLimits(min_call_interval_ms=30)
        )
        subject = runtime(executor, clock=now, trigger_policy=policy)
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await subject.wait_idle()

        corrected = active_turn("You mentioned Redis durability and failover")
        delayed = subject.observe_nowait(
            corrected,
            utterance("You mentioned Redis durability and failover", revision=2),
            memory_revision=0,
        )
        assert delayed.scheduled is True
        assert delayed.trigger_reason is PredictionTriggerReason.MINIMUM_CALL_INTERVAL
        await asyncio.sleep(0)
        assert len(executor.attempts) == 1

        await subject.wait_idle()
        assert len(executor.attempts) == 2
        assert executor.max_active_count == 1

    asyncio.run(scenario())


def test_many_meaningful_partials_are_coalesced_to_one_latest_attempt() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor([ExecutorScript(provider_result())])
        subject = runtime(executor, coalesce_seconds=0.03)
        latest = ""
        for revision in range(1, 41):
            latest = f"Can you explain Redis failure handling revision {revision}"
            subject.observe_nowait(
                active_turn(latest),
                utterance(latest, revision=revision),
                memory_revision=0,
            )

        await subject.wait_idle()

        assert len(executor.attempts) == 1
        assert executor.attempts[0].active_turn.text == latest
        assert executor.attempts[0].input_revision == 40
        assert subject.pending_task_count == 0

    asyncio.run(scenario())


def test_cancelled_cloud_attempt_waits_before_spending_on_next_revision() -> None:
    async def scenario() -> None:
        first_gate = asyncio.Event()
        executor = ControlledExecutor(
            [
                ExecutorScript(provider_result("Why Redis?"), gate=first_gate),
                ExecutorScript(provider_result("Why DynamoDB?")),
            ]
        )
        subject = runtime(
            executor,
            clock=lambda: round(time.monotonic() * 1_000),
            coalesce_seconds=0,
            cancelled_attempt_cooldown_seconds=0.08,
        )
        subject.observe_nowait(active_turn(), utterance(), memory_revision=0)
        await wait_for_attempts(executor, 1)

        revised = subject.observe_nowait(
            active_turn("You mentioned DynamoDB in your architecture"),
            utterance("You mentioned DynamoDB in your architecture", revision=2),
            memory_revision=0,
        )
        assert revised.snapshot.current is not None
        assert revised.snapshot.current.input_revision == 2
        assert revised.snapshot.current.state is PredictionState.SCHEDULED
        await asyncio.sleep(0.02)
        assert len(executor.attempts) == 1
        assert subject.snapshot().provider_attempt_count == 1

        await asyncio.wait_for(subject.wait_idle(), timeout=1)
        assert len(executor.attempts) == 2
        assert executor.max_active_count == 1
        assert subject.snapshot().state is PredictionState.READY
        assert subject.snapshot().current.candidates[0].text == "Why DynamoDB?"
        assert subject.snapshot().cancelled_call_count == 1
        assert subject.pending_task_count == 0

    asyncio.run(scenario())


def test_finalization_before_cancellation_cooldown_spends_only_one_call() -> None:
    async def scenario() -> None:
        executor = ControlledExecutor(
            [ExecutorScript(provider_result(), gate=asyncio.Event())]
        )
        subject = runtime(
            executor,
            clock=lambda: round(time.monotonic() * 1_000),
            coalesce_seconds=0,
            cancelled_attempt_cooldown_seconds=0.08,
        )
        current = active_turn()
        subject.observe_nowait(current, utterance(), memory_revision=0)
        await wait_for_attempts(executor, 1)
        subject.observe_nowait(
            active_turn("You mentioned DynamoDB in your architecture"),
            utterance("You mentioned DynamoDB in your architecture", revision=2),
            memory_revision=0,
        )
        subject.invalidate_turn_nowait(
            current.turn_id, reason=PredictionInvalidationReason.TURN_FINALIZED
        )
        await asyncio.wait_for(subject.wait_idle(), timeout=1)
        assert len(executor.attempts) == 1
        assert subject.snapshot().state is PredictionState.INVALIDATED
        assert subject.snapshot().cancelled_call_count == 1
        assert subject.pending_task_count == 0

    asyncio.run(scenario())
