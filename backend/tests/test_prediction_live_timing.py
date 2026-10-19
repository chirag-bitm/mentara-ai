"""Live timing checks complement the corpus's sequential fake-provider checks.

The timing scale is ten times faster than the measured Windows trace: a
50 ms test partial interval represents roughly 500 ms of microphone input.
These tests assess cancellation/readiness, not model quality or real latency.
"""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from uuid import UUID

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import ActiveConversationTurn, ContinuityQuality
from app.services.prediction import (
    DeterministicPredictionTriggerPolicy,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionInvalidationReason,
    PredictionProviderResult,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionState,
    PredictionTriggerPolicyLimits,
    PredictionTriggerReason,
)
from app.services.prediction.runtime import PredictionAttemptInput
from app.services.transcript.models import AudioSource, CanonicalUtterance, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000818")
UTTERANCE_ID = UUID("00000000-0000-0000-0000-000000000819")


class DelayedExecutor:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0
        self.cancelled = 0

    async def execute(self, attempt: PredictionAttemptInput) -> PredictionProviderResult:
        self.calls += 1
        try:
            await asyncio.sleep(self.delay_seconds)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return PredictionProviderResult(
            candidates=(
                PredictionCandidate(
                    kind=PredictionCandidateKind.QUESTION,
                    text="What happens when Redis is unavailable?",
                    anchor_terms=("redis",),
                ),
            )
        )


def _input(revision: int, *, observed_ms: int):
    text = (
        "You mentioned Redis in your architecture, "
        + "and I would like to understand "
        + ("the " * revision)
        + "failure behavior"
    )
    active = ActiveConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, 2),
        turn_sequence=2,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(2,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=observed_ms - 10,
        last_updated_ms=observed_ms,
        continuity_quality=ContinuityQuality.NORMAL,
        awaiting_finalization=False,
        pending_deadline_ms=None,
    )
    utterance = CanonicalUtterance(
        session_id=SESSION_ID,
        utterance_id=UTTERANCE_ID,
        sequence=2,
        revision=revision,
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        is_final=False,
        first_seen_ms=observed_ms - 10,
        last_updated_ms=observed_ms,
    )
    return active, utterance


def _runtime(
    executor: DelayedExecutor,
    *,
    coalesce_seconds: float,
    max_compatible_extension_chars: int = 0,
) -> PredictionRuntime:
    return PredictionRuntime(
        session_id=SESSION_ID,
        executor=executor,
        clock=lambda: round(monotonic() * 1_000),
        limits=PredictionRuntimeLimits(
            coalesce_seconds=coalesce_seconds,
            provider_timeout_seconds=0.5,
            max_attempts_per_turn=2,
            max_calls_per_session=64,
            cancelled_attempt_cooldown_seconds=0.4,
            max_compatible_extension_chars=max_compatible_extension_chars,
        ),
        trigger_policy=DeterministicPredictionTriggerPolicy(
            limits=PredictionTriggerPolicyLimits(min_call_interval_ms=120)
        ),
    )


def test_continuous_revisions_outpace_provider_without_showing_stale_candidate(
    caplog,
) -> None:
    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(executor, coalesce_seconds=0.035)
        events = []
        runtime.attach_sink(UUID(int=49), events.append)
        try:
            for revision in range(1, 9):
                active, utterance = _input(
                    revision, observed_ms=round(monotonic() * 1_000)
                )
                runtime.observe_nowait(active, utterance, memory_revision=1)
                # A 1.4 s initial gap permits the first call; later 0.5 s
                # partials cancel it and the 4 s cooldown covers finalization.
                await asyncio.sleep(0.14 if revision == 1 else 0.05)

            before_final = runtime.snapshot()
            assert executor.calls == 1
            assert before_final.cancelled_call_count == 1
            assert before_final.current is not None
            assert before_final.current.input_revision == 8
            assert all(event.state is not PredictionState.READY for event in events)

            runtime.invalidate_turn_nowait(
                active.turn_id, reason=PredictionInvalidationReason.TURN_FINALIZED
            )
            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            assert executor.cancelled == 1
            assert runtime.pending_task_count == 0
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()

    with caplog.at_level(logging.INFO, logger="app.services.prediction.runtime"):
        asyncio.run(scenario())
    assert "Prediction attempt cancelled:" in caplog.text
    assert "reason=active_input_changed" in caplog.text
    assert "request_to_cancel_ms=" in caplog.text
    assert "Redis" not in caplog.text


def test_provider_can_be_ready_only_if_input_remains_current_long_enough() -> None:
    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(executor, coalesce_seconds=0.035)
        try:
            active, utterance = _input(1, observed_ms=round(monotonic() * 1_000))
            runtime.observe_nowait(active, utterance, memory_revision=1)
            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            ready = runtime.snapshot().current
            assert ready is not None and ready.state is PredictionState.READY
            assert ready.input_revision == 1
            assert executor.calls == 1

            # Material correction clears the ready candidate immediately.
            corrected, source = _input(2, observed_ms=round(monotonic() * 1_000))
            changed = runtime.observe_nowait(corrected, source, memory_revision=1)
            assert changed.snapshot.current is not None
            assert changed.snapshot.current.input_revision == 2
            assert changed.snapshot.current.candidates == ()
            runtime.invalidate_turn_nowait(
                active.turn_id, reason=PredictionInvalidationReason.TURN_FINALIZED
            )
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()
            assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_late_started_attempt_survives_measured_neutral_stt_completion() -> None:
    """Replay the Windows shape where the paid call starts late in the preface."""

    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(
            executor,
            coalesce_seconds=0.035,
            max_compatible_extension_chars=96,
        )

        def observation(text: str, revision: int):
            observed_ms = round(monotonic() * 1_000)
            active = ActiveConversationTurn(
                session_id=SESSION_ID,
                turn_id=derive_turn_id(SESSION_ID, 2),
                turn_sequence=2,
                source_utterance_ids=(UTTERANCE_ID,),
                source_transcript_sequences=(2,),
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                started_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
                continuity_quality=ContinuityQuality.NORMAL,
                awaiting_finalization=False,
                pending_deadline_ms=None,
            )
            source = CanonicalUtterance(
                session_id=SESSION_ID,
                utterance_id=UTTERANCE_ID,
                sequence=2,
                revision=revision,
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                is_final=False,
                first_seen_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
            )
            return active, source

        try:
            basis = (
                "You mentioned Redis in your architecture "
                "and I am interested in the"
            )
            active, source = observation(basis, 1)
            runtime.observe_nowait(active, source, memory_revision=1)
            await asyncio.sleep(0.14)
            assert executor.calls == 1

            completed_preface = f"{basis} trade-offs"
            active, source = observation(completed_preface, 2)
            compatible = runtime.observe_nowait(
                active,
                source,
                memory_revision=1,
            )
            assert compatible.materially_changed is False
            assert compatible.scheduled is False

            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            ready = runtime.snapshot().current
            assert ready is not None and ready.state is PredictionState.READY
            assert ready.input_revision == 1
            assert executor.calls == 1
            assert executor.cancelled == 0
            assert runtime.turn_compatible_extension_count == 1

            question = f"{completed_preface} what happens if Redis fails"
            active, source = observation(question, 3)
            changed = runtime.observe_nowait(active, source, memory_revision=1)
            assert changed.materially_changed is True
            assert changed.snapshot.current is not None
            assert changed.snapshot.current.input_revision == 2
            assert changed.snapshot.current.candidates == ()
            runtime.invalidate_turn_nowait(
                active.turn_id,
                reason=PredictionInvalidationReason.TURN_FINALIZED,
            )
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()
            assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_compatible_provider_final_extension_preserves_running_attempt() -> None:
    """Provider-final is lifecycle metadata, not itself a text correction.

    A bounded append-only continuation may therefore keep the current attempt
    alive during M3's merge window.  The finalized ConversationTurn remains
    authoritative and will still invalidate the prediction separately.
    """

    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(
            executor,
            coalesce_seconds=0.035,
            max_compatible_extension_chars=96,
        )

        def observation(
            text: str,
            revision: int,
            *,
            awaiting_finalization: bool,
        ):
            observed_ms = round(monotonic() * 1_000)
            active = ActiveConversationTurn(
                session_id=SESSION_ID,
                turn_id=derive_turn_id(SESSION_ID, 2),
                turn_sequence=2,
                source_utterance_ids=(UTTERANCE_ID,),
                source_transcript_sequences=(2,),
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                started_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
                continuity_quality=ContinuityQuality.NORMAL,
                awaiting_finalization=awaiting_finalization,
                pending_deadline_ms=(observed_ms + 250 if awaiting_finalization else None),
            )
            source = CanonicalUtterance(
                session_id=SESSION_ID,
                utterance_id=UTTERANCE_ID,
                sequence=2,
                revision=revision,
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                is_final=awaiting_finalization,
                first_seen_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
                finalized_ms=(observed_ms if awaiting_finalization else None),
            )
            return active, source

        try:
            basis = "You mentioned Redis in your architecture"
            active, source = observation(
                basis,
                1,
                awaiting_finalization=False,
            )
            runtime.observe_nowait(active, source, memory_revision=1)
            await asyncio.sleep(0.14)
            assert executor.calls == 1

            active, source = observation(
                f"{basis} and I am interested in the trade-offs",
                2,
                awaiting_finalization=True,
            )
            compatible = runtime.observe_nowait(
                active,
                source,
                memory_revision=1,
            )
            assert compatible.materially_changed is False
            assert compatible.scheduled is False
            assert (
                compatible.trigger_reason
                is PredictionTriggerReason.COMPATIBLE_EXTENSION
            )

            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            ready = runtime.snapshot().current
            assert ready is not None and ready.state is PredictionState.READY
            assert ready.active_turn_awaiting_finalization is True
            assert executor.calls == 1
            assert executor.cancelled == 0
            assert runtime.turn_compatible_extension_count == 1

            runtime.invalidate_turn_nowait(
                active.turn_id,
                reason=PredictionInvalidationReason.TURN_FINALIZED,
            )
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()
            assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_provider_final_correction_still_cancels_running_attempt() -> None:
    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(
            executor,
            coalesce_seconds=0.035,
            max_compatible_extension_chars=96,
        )
        try:
            active, source = _input(1, observed_ms=round(monotonic() * 1_000))
            runtime.observe_nowait(active, source, memory_revision=1)
            await asyncio.sleep(0.14)
            assert executor.calls == 1

            observed_ms = round(monotonic() * 1_000)
            corrected_text = "Actually, let us discuss DynamoDB instead"
            corrected = ActiveConversationTurn(
                session_id=SESSION_ID,
                turn_id=active.turn_id,
                turn_sequence=active.turn_sequence,
                source_utterance_ids=active.source_utterance_ids,
                source_transcript_sequences=active.source_transcript_sequences,
                audio_source=active.audio_source,
                speaker_role=active.speaker_role,
                text=corrected_text,
                started_ms=active.started_ms,
                last_updated_ms=observed_ms,
                continuity_quality=ContinuityQuality.NORMAL,
                awaiting_finalization=True,
                pending_deadline_ms=observed_ms + 250,
            )
            corrected_source = CanonicalUtterance(
                session_id=SESSION_ID,
                utterance_id=UTTERANCE_ID,
                sequence=2,
                revision=2,
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=corrected_text,
                is_final=True,
                first_seen_ms=source.first_seen_ms,
                last_updated_ms=observed_ms,
                finalized_ms=observed_ms,
            )
            changed = runtime.observe_nowait(
                corrected,
                corrected_source,
                memory_revision=1,
            )
            assert changed.materially_changed is True
            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            assert executor.cancelled == 1
            assert runtime.snapshot().current is not None
            assert runtime.snapshot().current.candidates == ()
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()
            assert runtime.pending_task_count == 0

    asyncio.run(scenario())


def test_append_only_preface_can_finish_then_direct_question_clears_it() -> None:
    async def scenario() -> None:
        executor = DelayedExecutor(delay_seconds=0.28)
        runtime = _runtime(
            executor,
            coalesce_seconds=0.035,
            max_compatible_extension_chars=96,
        )
        events = []
        runtime.attach_sink(UUID(int=50), events.append)
        basis = "You mentioned Redis"

        def observation(text: str, revision: int):
            observed_ms = round(monotonic() * 1_000)
            active = ActiveConversationTurn(
                session_id=SESSION_ID,
                turn_id=derive_turn_id(SESSION_ID, 2),
                turn_sequence=2,
                source_utterance_ids=(UTTERANCE_ID,),
                source_transcript_sequences=(2,),
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                started_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
                continuity_quality=ContinuityQuality.NORMAL,
                awaiting_finalization=False,
                pending_deadline_ms=None,
            )
            utterance = CanonicalUtterance(
                session_id=SESSION_ID,
                utterance_id=UTTERANCE_ID,
                sequence=2,
                revision=revision,
                audio_source=AudioSource.MICROPHONE,
                speaker_role=SpeakerRole.LOCAL_USER,
                text=text,
                is_final=False,
                first_seen_ms=observed_ms - 10,
                last_updated_ms=observed_ms,
            )
            return active, utterance

        try:
            active, utterance = observation(basis, 1)
            runtime.observe_nowait(active, utterance, memory_revision=1)
            await asyncio.sleep(0.14)

            suffixes = (
                "in",
                "in your",
                "in your architecture",
                "in your architecture and",
                "in your architecture and I am interested",
                "in your architecture and I am interested in the tradeoffs",
            )
            for revision, suffix in enumerate(suffixes, start=2):
                active, utterance = observation(f"{basis} {suffix}", revision)
                submitted = runtime.observe_nowait(
                    active,
                    utterance,
                    memory_revision=1,
                )
                assert submitted.materially_changed is False
                await asyncio.sleep(0.05)

            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            ready = runtime.snapshot().current
            assert ready is not None and ready.state is PredictionState.READY
            assert ready.input_revision == 1
            assert executor.calls == 1
            assert executor.cancelled == 0
            assert any(event.state is PredictionState.READY for event in events)

            question = f"{active.text} what happens if Redis fails"
            changed_active, changed_utterance = observation(question, 8)
            changed = runtime.observe_nowait(
                changed_active,
                changed_utterance,
                memory_revision=1,
            )
            assert changed.materially_changed is True
            assert changed.snapshot.current is not None
            assert changed.snapshot.current.input_revision == 2
            assert changed.snapshot.current.candidates == ()

            runtime.invalidate_turn_nowait(
                changed_active.turn_id,
                reason=PredictionInvalidationReason.TURN_FINALIZED,
            )
            await asyncio.wait_for(runtime.wait_idle(), timeout=1)
            assert executor.calls == 1
        finally:
            runtime.shutdown_nowait()
            await runtime.wait_idle()
            assert runtime.pending_task_count == 0

    asyncio.run(scenario())
