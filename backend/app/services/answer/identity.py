from uuid import UUID, uuid5


def derive_answer_id(detection_id: UUID) -> UUID:
    """Derive one stable logical answer identity from an M3 detection."""

    return uuid5(detection_id, "mentara.answer.v1")
