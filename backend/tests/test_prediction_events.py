from dataclasses import replace
from uuid import UUID

from app.schemas.events import prediction_event_from_snapshot
from app.services.conversation.models import ContinuityQuality
from app.services.prediction import (
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionInvalidationReason,
    PredictionReadiness,
    PredictionSnapshot,
    PredictionState,
    PredictionUsage,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
PREDICTION_ID = UUID("10000000-0000-0000-0000-000000000001")
TURN_ID = UUID("20000000-0000-0000-0000-000000000001")


def _scheduled() -> PredictionSnapshot:
    return PredictionSnapshot(
        prediction_id=PREDICTION_ID,
        session_id=SESSION_ID,
        active_turn_id=TURN_ID,
        active_turn_sequence=4,
        input_revision=2,
        attempt=0,
        state=PredictionState.SCHEDULED,
        snapshot_revision=1,
        material_fingerprint="a" * 64,
        memory_revision=7,
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        continuity_quality=ContinuityQuality.NORMAL,
        active_turn_awaiting_finalization=False,
        candidate_consistent_revision_count=0,
        candidates=(),
        input_observed_ms=100,
        scheduled_ms=101,
    )


def test_prediction_event_exposes_bounded_advisory_output_not_internal_memory_revision() -> None:
    candidate = PredictionCandidate(
        kind=PredictionCandidateKind.QUESTION,
        text="Why did you choose Redis?",
        anchor_terms=("redis",),
    )
    ready = replace(
        _scheduled(),
        attempt=1,
        state=PredictionState.READY,
        snapshot_revision=3,
        provider_started_ms=102,
        ready_ms=120,
        candidate_consistent_revision_count=1,
        candidates=(candidate,),
        readiness=PredictionReadiness.TENTATIVE,
        usage=PredictionUsage(input_tokens=30, output_tokens=8, total_tokens=38),
        context_chars=320,
    )

    event = prediction_event_from_snapshot(ready)
    payload = event.model_dump(mode="json", exclude_none=True)

    assert payload["type"] == "prediction.snapshot"
    assert payload["candidates"] == [
        {
            "kind": "question",
            "text": "Why did you choose Redis?",
            "anchor_terms": ["redis"],
        }
    ]
    assert payload["readiness"] == "tentative"
    assert payload["context_chars"] == 320
    assert "memory_revision" not in payload


def test_memory_version_invalidation_is_projected_as_generic_context_change() -> None:
    invalidated = replace(
        _scheduled(),
        state=PredictionState.INVALIDATED,
        snapshot_revision=2,
        terminal_ms=110,
        invalidation_reason=PredictionInvalidationReason.MEMORY_REVISION_CHANGED,
    )

    event = prediction_event_from_snapshot(invalidated)

    assert event.invalidation_reason == "context_changed"
    assert event.candidates == []

