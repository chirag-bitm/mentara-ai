"""Provider-neutral answer generation domain and service boundaries."""

from app.services.answer.context import (
    AnswerContextAssembler,
    BoundedAnswerContextAssembler,
    MemoryAnswerContextAssembler,
)
from app.services.answer.fake import FakeAnswerProvider, FakeAnswerScript
from app.services.answer.identity import derive_answer_id
from app.services.answer.lifecycle import AnswerLifecycle, InvalidAnswerTransition
from app.services.answer.models import (
    AnswerContext,
    AnswerContextTurn,
    AnswerFailure,
    AnswerFailureCategory,
    AnswerPrompt,
    AnswerProviderCompleted,
    AnswerProviderEvent,
    AnswerProviderTextDelta,
    AnswerRequest,
    AnswerSessionSnapshot,
    AnswerSnapshot,
    AnswerState,
    AnswerUsage,
)
from app.services.answer.policy import AnswerPolicy, ConciseAnswerPolicy
from app.services.answer.provider import (
    AnswerProvider,
    AnswerProviderError,
    AnswerProviderRequest,
    AnswerProviderStream,
)
from app.services.answer.request import build_answer_request
from app.services.answer.runtime import AnswerRuntime, AnswerSubmission

__all__ = [
    "AnswerContext",
    "AnswerContextAssembler",
    "AnswerContextTurn",
    "AnswerFailure",
    "AnswerFailureCategory",
    "AnswerLifecycle",
    "AnswerPolicy",
    "AnswerPrompt",
    "AnswerProvider",
    "AnswerProviderCompleted",
    "AnswerProviderError",
    "AnswerProviderEvent",
    "AnswerProviderRequest",
    "AnswerProviderStream",
    "AnswerProviderTextDelta",
    "AnswerRequest",
    "AnswerRuntime",
    "AnswerSessionSnapshot",
    "AnswerSnapshot",
    "AnswerState",
    "AnswerSubmission",
    "AnswerUsage",
    "BoundedAnswerContextAssembler",
    "ConciseAnswerPolicy",
    "FakeAnswerProvider",
    "FakeAnswerScript",
    "InvalidAnswerTransition",
    "MemoryAnswerContextAssembler",
    "build_answer_request",
    "derive_answer_id",
]
