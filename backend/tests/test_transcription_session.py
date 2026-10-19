from collections.abc import Callable
from uuid import UUID

import pytest

from app.services.conversation.models import ContinuityQuality
from app.services.stt.base import TranscriptResult
from app.services.transcript.aggregator import TranscriptAggregator
from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
UTTERANCE_ONE = UUID("10000000-0000-0000-0000-000000000001")
UTTERANCE_TWO = UUID("10000000-0000-0000-0000-000000000002")


def id_factory(*values: UUID) -> Callable[[], UUID]:
    remaining = iter(values)
    return lambda: next(remaining)


def result(text: str, *, is_final: bool = False) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        is_final=is_final,
        speech_final=is_final,
    )


def make_session() -> TranscriptionSession:
    return TranscriptionSession(
        aggregator=TranscriptAggregator(
            session_id=SESSION_ID,
            utterance_id_factory=id_factory(UTTERANCE_ONE, UTTERANCE_TWO),
        )
    )


def test_session_starts_connecting_without_a_provider_generation() -> None:
    session = make_session()

    snapshot = session.snapshot()

    assert snapshot.session_id == SESSION_ID
    assert snapshot.connection_state is SessionConnectionState.CONNECTING
    assert snapshot.provider_generation == 0
    assert snapshot.transcript.sequence == 0


def test_provider_replacement_preserves_session_and_finalized_history() -> None:
    session = make_session()
    session.transition(SessionConnectionState.CONNECTED)
    partial = session.apply(result("First"))
    final = session.apply(result("First sentence.", is_final=True))

    session.transition(SessionConnectionState.RECONNECTING)
    reconnecting = session.snapshot()
    session.transition(SessionConnectionState.CONNECTED)
    second = session.apply(result("Second sentence."))
    recovered = session.snapshot()

    assert partial is not None
    assert final is not None
    assert second is not None
    assert reconnecting.session_id == SESSION_ID
    assert reconnecting.provider_generation == 1
    assert reconnecting.transcript.finalized_utterances == (final,)
    assert recovered.session_id == SESSION_ID
    assert recovered.provider_generation == 2
    assert recovered.transcript.finalized_utterances == (final,)
    assert second.sequence == 3
    assert second.utterance_id == UTTERANCE_TWO


def test_idempotent_state_transition_does_not_increment_generation() -> None:
    session = make_session()

    first = session.transition(SessionConnectionState.CONNECTED)
    repeated = session.transition(SessionConnectionState.CONNECTED)

    assert first.provider_generation == 1
    assert repeated.provider_generation == 1


def test_invalid_transition_is_rejected_without_changing_state() -> None:
    session = make_session()

    with pytest.raises(ValueError, match="connecting -> reconnecting"):
        session.transition(SessionConnectionState.RECONNECTING)

    assert session.connection_state is SessionConnectionState.CONNECTING


def test_stopped_session_is_terminal() -> None:
    session = make_session()
    session.transition(SessionConnectionState.STOPPED)

    with pytest.raises(ValueError, match="stopped -> connected"):
        session.transition(SessionConnectionState.CONNECTED)

    assert session.connection_state is SessionConnectionState.STOPPED


def test_session_reset_clears_conversation_and_detection_state() -> None:
    session = make_session()
    final = session.apply(result("What is Redis?", is_final=True))
    assert final is not None
    session.turn_engine.observe(
        final,
        continuity_quality=ContinuityQuality.NORMAL,
    )
    turn = session.turn_engine.finalize_due(now_ms=250)
    assert turn is not None
    decision = session.detect_assistance(turn, detected_ms=250)
    assert decision is not None and decision.should_assist is True

    snapshot = session.reset()
    assert snapshot.connection_state is SessionConnectionState.CONNECTING
    assert snapshot.provider_generation == 0
    assert snapshot.transcript.finalized_utterances == ()
    assert snapshot.conversation.finalized_turns == ()
    assert snapshot.conversation.assistance_detections == ()
