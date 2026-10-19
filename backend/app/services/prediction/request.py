from app.services.conversation.models import ActiveConversationTurn
from app.services.prediction.identity import (
    derive_prediction_id,
    derive_prediction_input_fingerprint,
)
from app.services.prediction.models import PredictionContext, PredictionRequest
from app.services.transcript.models import CanonicalUtterance


def build_prediction_request(
    active_turn: ActiveConversationTurn,
    triggering_utterance: CanonicalUtterance,
    context: PredictionContext,
    *,
    input_revision: int,
    attempt: int,
    requested_ms: int,
    input_observed_ms: int | None = None,
) -> PredictionRequest:
    """Build one attempt from canonical/M3 state and read-only planned context."""

    if triggering_utterance.session_id != active_turn.session_id:
        raise ValueError("triggering utterance and active turn must share a session")
    if triggering_utterance.utterance_id not in active_turn.source_utterance_ids:
        raise ValueError("triggering utterance is not part of the active turn")
    if (
        triggering_utterance.audio_source is not active_turn.audio_source
        or triggering_utterance.speaker_role is not active_turn.speaker_role
    ):
        raise ValueError(
            "triggering utterance source/speaker does not match active turn"
        )
    source_index = active_turn.source_utterance_ids.index(
        triggering_utterance.utterance_id
    )
    if (
        active_turn.source_transcript_sequences[source_index]
        != triggering_utterance.sequence
    ):
        raise ValueError("triggering utterance sequence does not match active turn")

    prediction_id = derive_prediction_id(active_turn.session_id, active_turn.turn_id)
    if context.prediction_id != prediction_id:
        raise ValueError("prediction context identity does not match active turn")
    if context.active_turn.turn_id != active_turn.turn_id:
        raise ValueError("prediction context does not contain the active turn")
    if context.input_revision != input_revision:
        raise ValueError("prediction context input revision does not match")
    context_active = context.active_turn
    active_text_matches = (
        context_active.text == active_turn.text
        if not context_active.text_truncated
        else active_turn.text.startswith(context_active.text.removesuffix("…"))
    )
    if (
        context_active.turn_sequence != active_turn.turn_sequence
        or context_active.source_utterance_ids != active_turn.source_utterance_ids
        or context_active.source_transcript_sequences
        != active_turn.source_transcript_sequences
        or context_active.audio_source is not active_turn.audio_source
        or context_active.speaker_role is not active_turn.speaker_role
        or context_active.continuity_quality is not active_turn.continuity_quality
        or context_active.original_text_chars != len(active_turn.text)
        or not active_text_matches
    ):
        raise ValueError("prediction context active-turn provenance does not match")

    observed_ms = (
        active_turn.last_updated_ms
        if input_observed_ms is None
        else input_observed_ms
    )
    if observed_ms < active_turn.last_updated_ms:
        raise ValueError("prediction observation cannot precede active input")
    if requested_ms < observed_ms:
        raise ValueError("prediction request cannot precede observation")

    fingerprint = derive_prediction_input_fingerprint(
        active_turn,
        memory_revision=context.memory_revision,
    )
    return PredictionRequest(
        prediction_id=prediction_id,
        session_id=active_turn.session_id,
        active_turn_id=active_turn.turn_id,
        active_turn_sequence=active_turn.turn_sequence,
        input_revision=input_revision,
        attempt=attempt,
        material_fingerprint=fingerprint,
        memory_revision=context.memory_revision,
        source_utterance_ids=active_turn.source_utterance_ids,
        source_transcript_sequences=active_turn.source_transcript_sequences,
        triggering_utterance_id=triggering_utterance.utterance_id,
        triggering_transcript_sequence=triggering_utterance.sequence,
        triggering_transcript_revision=triggering_utterance.revision,
        triggering_utterance_is_final=triggering_utterance.is_final,
        audio_source=active_turn.audio_source,
        speaker_role=active_turn.speaker_role,
        continuity_quality=active_turn.continuity_quality,
        active_turn_started_ms=active_turn.started_ms,
        input_observed_ms=observed_ms,
        requested_ms=requested_ms,
        active_turn_to_prediction_request_ms=requested_ms - active_turn.started_ms,
        context=context,
    )
