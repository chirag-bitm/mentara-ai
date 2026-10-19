from uuid import UUID, uuid5


def derive_turn_id(session_id: UUID, turn_sequence: int) -> UUID:
    """Derive replay-stable turn identity from canonical session order."""

    if turn_sequence < 1:
        raise ValueError("turn_sequence must start at 1")
    return uuid5(session_id, f"mentara.conversation-turn.v1:{turn_sequence}")


def derive_assistance_detection_id(turn_id: UUID) -> UUID:
    """One stable assistance decision identity per immutable finalized turn."""

    return uuid5(turn_id, "mentara.assistance-decision.v1")
