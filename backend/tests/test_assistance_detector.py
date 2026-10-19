from uuid import UUID

import pytest

from app.services.conversation.detector import (
    AssistanceDetectionEngine,
    LocalHeuristicAssistanceDetector,
)
from app.services.conversation.identity import derive_turn_id
from app.services.conversation.models import (
    AssistanceKind,
    ContinuityQuality,
    ConversationTurn,
    TurnFinalizationReason,
)
from app.services.transcript.models import AudioSource, SpeakerRole


SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
UTTERANCE_ID = UUID("10000000-0000-0000-0000-000000000001")


def turn(text: str, sequence: int = 1) -> ConversationTurn:
    return ConversationTurn(
        session_id=SESSION_ID,
        turn_id=derive_turn_id(SESSION_ID, sequence),
        turn_sequence=sequence,
        source_utterance_ids=(UTTERANCE_ID,),
        source_transcript_sequences=(sequence,),
        audio_source=AudioSource.MICROPHONE,
        speaker_role=SpeakerRole.LOCAL_USER,
        text=text,
        started_ms=0,
        last_updated_ms=100,
        source_finalized_ms=100,
        finalized_ms=350,
        finalization_reason=TurnFinalizationReason.MERGE_WINDOW_ELAPSED,
        continuity_quality=ContinuityQuality.NORMAL,
        transcript_final_to_turn_ms=250,
    )


@pytest.mark.parametrize(
    ("text", "kind"),
    (
        ("What is Redis?", AssistanceKind.QUESTION),
        ("Why did you choose Redis?", AssistanceKind.QUESTION),
        ("How would you design this?", AssistanceKind.QUESTION),
        ("Can you explain your project?", AssistanceKind.REQUEST),
        ("Tell me about yourself.", AssistanceKind.REQUEST),
        ("Walk me through your architecture.", AssistanceKind.REQUEST),
        ("Describe a difficult problem you solved.", AssistanceKind.REQUEST),
        ("Compare REST and GraphQL.", AssistanceKind.REQUEST),
        ("Suppose Redis becomes unavailable.", AssistanceKind.REQUEST),
        ("Could you elaborate?", AssistanceKind.REQUEST),
        ("Give me an example.", AssistanceKind.REQUEST),
        (
            "Give eight short differences between a process and a thread.",
            AssistanceKind.REQUEST,
        ),
        ("Provide a concise summary.", AssistanceKind.REQUEST),
        ("Write a short response for the stakeholder.", AssistanceKind.REQUEST),
        ("Draft an explanation of the delay.", AssistanceKind.REQUEST),
        ("Suggest three possible approaches.", AssistanceKind.REQUEST),
        ("Recommend the safest option.", AssistanceKind.REQUEST),
        ("Solve this recurrence relation.", AssistanceKind.REQUEST),
        ("Calculate the approximate latency.", AssistanceKind.REQUEST),
        ("Create a short checklist.", AssistanceKind.REQUEST),
        ("Check this reasoning for mistakes.", AssistanceKind.REQUEST),
        ("Identify the likely failure mode.", AssistanceKind.REQUEST),
        ("Find the difference between these designs.", AssistanceKind.REQUEST),
        ("Generate three interview follow-ups.", AssistanceKind.REQUEST),
        ("Prepare a brief explanation.", AssistanceKind.REQUEST),
        ("Rewrite this in simpler language.", AssistanceKind.REQUEST),
        ("Translate this sentence into Hindi.", AssistanceKind.REQUEST),
        ("Please provide a concise answer.", AssistanceKind.REQUEST),
        ("Kindly summarize the trade-offs.", AssistanceKind.REQUEST),
        ("Please can you explain this", AssistanceKind.REQUEST),
        ("What else", AssistanceKind.QUESTION),
        ("Why?", AssistanceKind.QUESTION),
        ("Agar Redis unavailable ho jaye toh fallback kaise handle karoge?", AssistanceKind.QUESTION),
        ("Redis fail ho to kya hoga?", AssistanceKind.QUESTION),
        ("अगर Redis unavailable हो जाए तो fallback कैसे handle करोगे?", AssistanceKind.QUESTION),
        ("Explain karo Redis ka fallback.", AssistanceKind.REQUEST),
        ("Agar Redis unavailable ho jaye toh fallback kaise handle karoge", AssistanceKind.QUESTION),
        ("The cache failed. What happens next", AssistanceKind.QUESTION),
    ),
)
def test_meaningful_questions_and_requests_are_detected(
    text: str,
    kind: AssistanceKind,
) -> None:
    decision = LocalHeuristicAssistanceDetector().detect(
        turn(text),
        detected_ms=351,
    )
    assert decision.should_assist is True
    assert decision.kind is kind
    assert decision.turn_to_detection_ms == 1


@pytest.mark.parametrize(
    "text",
    (
        "okay",
        "okay?",
        "right",
        "yes",
        "thanks",
        "got it",
        "thik hai",
        "हाँ",
        "The deployment completed successfully.",
        "Redis stores the cached value.",
        "I can explain Redis.",
        "Can be done.",
        "Giving feedback improves teams.",
        "The draft is ready.",
        "The process gives eight results.",
        "I recommend the safer option.",
        "Please note the deployment completed.",
        "interesting",
    ),
)
def test_backchannels_and_ordinary_statements_are_suppressed(text: str) -> None:
    decision = LocalHeuristicAssistanceDetector().detect(
        turn(text),
        detected_ms=350,
    )
    assert decision.should_assist is False
    assert decision.kind is AssistanceKind.NONE


def test_multi_sentence_turn_is_detected_without_requiring_final_question_mark() -> None:
    decision = LocalHeuristicAssistanceDetector().detect(
        turn("The cache failed yesterday. Explain how you would recover it."),
        detected_ms=352,
    )
    assert decision.should_assist is True
    assert decision.kind is AssistanceKind.REQUEST


def test_detection_engine_is_idempotent_and_retains_only_positive_replay_events() -> None:
    subject = AssistanceDetectionEngine()
    meaningful = turn("What happens if the cache fails?", sequence=1)
    statement = turn("The cache is healthy.", sequence=2)

    first = subject.observe(meaningful, detected_ms=350)
    duplicate = subject.observe(meaningful, detected_ms=400)
    negative = subject.observe(statement, detected_ms=350)

    assert first is not None and first.should_assist is True
    assert duplicate is None
    assert negative is not None and negative.should_assist is False
    assert subject.positive_decisions() == (first,)


def test_detection_rejects_time_before_turn_finalization() -> None:
    with pytest.raises(ValueError, match="precede"):
        LocalHeuristicAssistanceDetector().detect(
            turn("What is Redis?"),
            detected_ms=349,
        )
