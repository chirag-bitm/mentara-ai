"""Provider-neutral, non-authoritative predictive next-turn contracts."""

from app.services.prediction.identity import (
    derive_prediction_id,
    derive_prediction_input_fingerprint,
    normalize_prediction_input_text,
)
from app.services.prediction.executor import PredictionProviderExecutor
from app.services.prediction.fake import FakePredictionProvider, FakePredictionScript
from app.services.prediction.factory import create_prediction_provider
from app.services.prediction.gemini import GeminiPredictionProvider
from app.services.prediction.context import (
    DeterministicPredictionContextPlanner,
    PredictionContextPlanner,
    PredictionContextPlannerLimits,
)
from app.services.prediction.compatibility import (
    ConservativeAppendOnlyPredictionCompatibilityPolicy,
    PredictionInputCompatibilityLimits,
    PredictionInputCompatibilityPolicy,
)
from app.services.prediction.lifecycle import (
    InvalidPredictionTransition,
    PredictionLifecycle,
)
from app.services.prediction.models import (
    MAX_PREDICTION_ANCHOR_TERM_CHARS,
    MAX_PREDICTION_ANCHOR_TERMS,
    MAX_PREDICTION_CANDIDATE_CHARS,
    MAX_PREDICTION_CANDIDATES,
    MAX_PREDICTION_CONTEXT_CHARS,
    MAX_PREDICTION_CONTEXT_TURN_CHARS,
    MAX_PREDICTION_OUTPUT_TOKENS,
    PredictionCandidate,
    PredictionCandidateKind,
    PredictionContext,
    PredictionContextSelectionReason,
    PredictionContextTurn,
    PredictionFailure,
    PredictionFailureCategory,
    PredictionInvalidationReason,
    PredictionPrompt,
    PredictionReadiness,
    PredictionRequest,
    PredictionSessionSnapshot,
    PredictionSnapshot,
    PredictionState,
    PredictionTriggerReason,
    PredictionUsage,
)
from app.services.prediction.provider import (
    EventLoopIsolatedPredictionProvider,
    PredictionProvider,
    PredictionProviderError,
    PredictionProviderRequest,
    PredictionProviderResult,
)
from app.services.prediction.policy import LikelyNextTurnPolicy, PredictionPolicy
from app.services.prediction.request import build_prediction_request
from app.services.prediction.runtime import (
    PredictionAttemptExecutor,
    PredictionAttemptInput,
    PredictionRuntime,
    PredictionRuntimeLimits,
    PredictionSubmission,
)
from app.services.prediction.trigger import (
    DeterministicPredictionTriggerPolicy,
    PredictionTriggerDecision,
    PredictionTriggerPolicy,
    PredictionTriggerPolicyLimits,
)

__all__ = [
    "MAX_PREDICTION_ANCHOR_TERM_CHARS",
    "MAX_PREDICTION_ANCHOR_TERMS",
    "MAX_PREDICTION_CANDIDATE_CHARS",
    "MAX_PREDICTION_CANDIDATES",
    "MAX_PREDICTION_CONTEXT_CHARS",
    "MAX_PREDICTION_CONTEXT_TURN_CHARS",
    "MAX_PREDICTION_OUTPUT_TOKENS",
    "PredictionCandidate",
    "PredictionCandidateKind",
    "ConservativeAppendOnlyPredictionCompatibilityPolicy",
    "PredictionInputCompatibilityLimits",
    "PredictionInputCompatibilityPolicy",
    "DeterministicPredictionContextPlanner",
    "PredictionContextPlanner",
    "PredictionContextPlannerLimits",
    "PredictionContext",
    "PredictionContextSelectionReason",
    "PredictionContextTurn",
    "PredictionProviderExecutor",
    "FakePredictionProvider",
    "FakePredictionScript",
    "GeminiPredictionProvider",
    "EventLoopIsolatedPredictionProvider",
    "create_prediction_provider",
    "PredictionFailure",
    "PredictionFailureCategory",
    "PredictionInvalidationReason",
    "InvalidPredictionTransition",
    "PredictionLifecycle",
    "PredictionPrompt",
    "PredictionProvider",
    "PredictionProviderError",
    "PredictionProviderRequest",
    "PredictionProviderResult",
    "PredictionPolicy",
    "LikelyNextTurnPolicy",
    "PredictionReadiness",
    "PredictionRequest",
    "PredictionAttemptExecutor",
    "PredictionAttemptInput",
    "PredictionRuntime",
    "PredictionRuntimeLimits",
    "PredictionSubmission",
    "PredictionSessionSnapshot",
    "PredictionSnapshot",
    "PredictionState",
    "PredictionTriggerReason",
    "DeterministicPredictionTriggerPolicy",
    "PredictionTriggerDecision",
    "PredictionTriggerPolicy",
    "PredictionTriggerPolicyLimits",
    "PredictionUsage",
    "build_prediction_request",
    "derive_prediction_id",
    "derive_prediction_input_fingerprint",
    "normalize_prediction_input_text",
]
