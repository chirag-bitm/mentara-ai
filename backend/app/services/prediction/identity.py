import hashlib
import json
import unicodedata
from uuid import UUID, uuid5

from app.services.conversation.models import ActiveConversationTurn


def derive_prediction_id(session_id: UUID, active_turn_id: UUID) -> UUID:
    """Derive one stable logical prediction identity per active logical turn."""

    return uuid5(session_id, f"mentara.prediction.v1:{active_turn_id}")


def normalize_prediction_input_text(text: str) -> str:
    """Normalize only for material-change detection, never transcript truth."""

    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def derive_prediction_input_fingerprint(
    active_turn: ActiveConversationTurn,
    *,
    memory_revision: int,
) -> str:
    """Hash semantic/provenance inputs without logging or replacing provenance."""

    if memory_revision < 0:
        raise ValueError("memory_revision must not be negative")
    payload = {
        "audio_source": active_turn.audio_source.value,
        "continuity_quality": active_turn.continuity_quality.value,
        "memory_revision": memory_revision,
        "normalized_text": normalize_prediction_input_text(active_turn.text),
        "session_id": str(active_turn.session_id),
        # Canonical transcript sequences advance on partial revisions and on the
        # same-text provider-final event. Stable utterance IDs preserve source
        # identity here; exact sequences remain explicit request provenance.
        "source_utterance_ids": tuple(map(str, active_turn.source_utterance_ids)),
        "speaker_role": active_turn.speaker_role.value,
        "turn_id": str(active_turn.turn_id),
        "turn_sequence": active_turn.turn_sequence,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()
