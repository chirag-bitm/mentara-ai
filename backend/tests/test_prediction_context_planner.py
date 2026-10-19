from dataclasses import replace
from uuid import UUID

import pytest

from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import (
    ActiveConversationTurn,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.memory import (
    ContextTrust,
    ConversationMemory,
    MemoryContinuity,
    MemoryLimits,
)
from app.services.prediction import (
    DeterministicPredictionContextPlanner,
    PredictionContextPlannerLimits,
    PredictionContextSelectionReason,
    derive_prediction_id,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("32000000-0000-0000-0000-000000000001")
OTHER_SESSION_ID = UUID("32000000-0000-0000-0000-000000000002")


def _turn(
    sequence: int,
    text: str,
    *,
    session_id: UUID = SESSION_ID,
    continuity: ContinuityQuality = ContinuityQuality.NORMAL,
) -> ConversationTurn:
    base = sequence * 100
    return ConversationTurn(
        session_id=session_id,
        turn_id=derive_turn_id(session_id, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence),),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=base,
        last_updated_ms=base + 10,
        source_finalized_ms=base + 10,
        finalized_ms=base + 20,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=continuity,
        transcript_final_to_turn_ms=10,
    )


def _memory(
    *texts: str,
    limits: MemoryLimits | None = None,
) -> ConversationMemory:
    memory = ConversationMemory(session_id=SESSION_ID, limits=limits)
    for sequence, text in enumerate(texts, start=1):
        memory.observe(_turn(sequence, text))
    return memory


def _active(
    sequence: int,
    text: str,
    *,
    session_id: UUID = SESSION_ID,
    audio_source: AudioSource = AudioSource.MICROPHONE,
    speaker_role: SpeakerRole = SpeakerRole.LOCAL_USER,
) -> ActiveConversationTurn:
    return ActiveConversationTurn(
        session_id=session_id,
        turn_id=derive_turn_id(session_id, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UUID(int=sequence + 1000),),
        source_transcript_sequences=(sequence + 1000,),
        audio_source=audio_source,
        speaker_role=speaker_role,
        text=text,
        started_ms=sequence * 100,
        last_updated_ms=sequence * 100 + 20,
        continuity_quality=ContinuityQuality.NORMAL,
        awaiting_finalization=False,
        pending_deadline_ms=None,
    )


def test_active_recent_and_relevant_older_context_are_selected_read_only() -> None:
    memory = _memory(
        "Redis provides the cache and session read path.",
        "The service deploys across three availability zones.",
        "Our CI pipeline runs unit and integration tests.",
        "The release requires approval from the platform team.",
    )
    snapshot = memory.snapshot()
    active = _active(5, "Coming back to Redis, why not use DynamoDB instead?")

    first = DeterministicPredictionContextPlanner().plan(
        snapshot,
        active,
        input_revision=3,
    )
    second = DeterministicPredictionContextPlanner().plan(
        snapshot,
        active,
        input_revision=3,
    )

    assert first == second
    assert first.prediction_id == derive_prediction_id(SESSION_ID, active.turn_id)
    assert first.memory_revision == snapshot.memory_revision
    assert [turn.turn_sequence for turn in first.recent_memory] == [3, 4]
    assert [turn.turn_sequence for turn in first.relevant_older_memory] == [1]
    assert first.active_turn.text == active.text
    assert memory.snapshot() == snapshot
    assert all(
        turn.trust is ContextTrust.UNTRUSTED
        for turn in (
            first.active_turn,
            *first.recent_memory,
            *first.relevant_older_memory,
        )
    )


def test_active_turn_has_priority_and_total_context_is_hard_bounded() -> None:
    memory = _memory("a" * 100, "b" * 100, "c" * 100)
    active = _active(4, "active " * 30)
    planner = DeterministicPredictionContextPlanner(
        limits=PredictionContextPlannerLimits(
            max_recent_turns=2,
            max_relevant_older_turns=2,
            max_total_text_chars=80,
            max_active_turn_chars=50,
            max_memory_turn_chars=25,
        )
    )

    context = planner.plan(memory.snapshot(), active, input_revision=1)

    assert len(context.active_turn.text) == 50
    assert context.active_turn.text_truncated is True
    assert context.active_turn.original_text_chars == len(active.text)
    assert context.total_text_chars == 80
    assert all(len(turn.text) <= 25 for turn in context.recent_memory)


def test_only_memory_preceding_active_turn_can_be_selected() -> None:
    memory = _memory("first", "second", "third", "future fourth", "future fifth")

    context = DeterministicPredictionContextPlanner().plan(
        memory.snapshot(),
        _active(4, "Can you explain the earlier design choice?"),
        input_revision=1,
    )

    assert [turn.turn_sequence for turn in context.recent_memory] == [2, 3]
    assert all(
        turn.turn_sequence < 4
        for turn in context.recent_memory + context.relevant_older_memory
    )


def test_missing_anchor_does_not_fabricate_relevant_older_memory() -> None:
    memory = _memory(
        "Redis handles session caching.",
        "The deployment uses three zones.",
        "The release was approved yesterday.",
    )

    context = DeterministicPredictionContextPlanner(
        limits=PredictionContextPlannerLimits(
            max_recent_turns=1,
            max_relevant_older_turns=2,
        )
    ).plan(
        memory.snapshot(),
        _active(4, "Can you explain that part in more detail?"),
        input_revision=1,
    )

    assert [turn.turn_sequence for turn in context.recent_memory] == [3]
    assert context.relevant_older_memory == ()


def test_memory_gap_and_eviction_evidence_are_preserved() -> None:
    memory = ConversationMemory(
        session_id=SESSION_ID,
        limits=MemoryLimits(
            max_retained_turns=2,
            max_retained_text_chars=1_000,
            max_entry_text_chars=200,
        ),
    )
    memory.observe(_turn(1, "Redis cache design."))
    memory.observe(_turn(3, "A later deployment topic."))
    memory.observe(_turn(4, "The most recent release topic."))
    snapshot = memory.snapshot()
    assert snapshot.continuity is MemoryContinuity.DEGRADED

    context = DeterministicPredictionContextPlanner().plan(
        snapshot,
        _active(5, "What happens if the cache design fails?"),
        input_revision=2,
    )

    assert context.memory_continuity is MemoryContinuity.DEGRADED
    assert context.evicted_turn_count == 1
    assert context.missing_turn_count == 1


def test_context_preserves_source_and_speaker_neutral_active_provenance() -> None:
    active = _active(
        1,
        "Could you explain the remote system design?",
        audio_source=AudioSource.SYSTEM,
        speaker_role=SpeakerRole.REMOTE_SPEAKER,
    )
    memory = ConversationMemory(session_id=SESSION_ID)

    context = DeterministicPredictionContextPlanner().plan(
        memory.snapshot(),
        active,
        input_revision=1,
    )

    assert context.active_turn.audio_source is AudioSource.SYSTEM
    assert context.active_turn.speaker_role is SpeakerRole.REMOTE_SPEAKER
    assert context.active_turn.source_utterance_ids == active.source_utterance_ids


def test_cross_session_context_is_rejected() -> None:
    memory = ConversationMemory(session_id=SESSION_ID)
    active = _active(1, "Can you explain the architecture?", session_id=OTHER_SESSION_ID)

    with pytest.raises(ValueError, match="share a session"):
        DeterministicPredictionContextPlanner().plan(
            memory.snapshot(),
            active,
            input_revision=1,
        )


def test_planner_handles_many_memory_turns_with_constant_output_bounds() -> None:
    memory = _memory(*(f"Archived topic number {index}" for index in range(100)))
    planner = DeterministicPredictionContextPlanner()

    context = planner.plan(
        memory.snapshot(),
        _active(101, "Returning to archived topic number five, what changed?"),
        input_revision=1,
    )

    assert len(context.recent_memory) <= 2
    assert len(context.relevant_older_memory) <= 2
    assert context.total_text_chars <= 3_200


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_recent_turns": -1},
        {"max_relevant_older_turns": -1},
        {"max_total_text_chars": 0},
        {"max_total_text_chars": 6_001},
        {"max_active_turn_chars": 0},
        {"max_memory_turn_chars": 4_001},
        {"max_total_text_chars": 100, "max_active_turn_chars": 101},
        {"max_total_text_chars": 100, "max_memory_turn_chars": 101},
    ],
)
def test_invalid_context_planner_limits_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        PredictionContextPlannerLimits(**kwargs)


def test_active_input_object_is_not_modified() -> None:
    memory = _memory("Recent untrusted context.")
    active = _active(2, "Can you explain the context selection?")
    before = replace(active)

    DeterministicPredictionContextPlanner().plan(
        memory.snapshot(),
        active,
        input_revision=1,
    )

    assert active == before
