from __future__ import annotations

from collections.abc import Callable

from app.services.prediction.models import (
    MAX_PREDICTION_CANDIDATES,
    MAX_PREDICTION_OUTPUT_TOKENS,
    PredictionFailureCategory,
)
from app.services.prediction.policy import LikelyNextTurnPolicy, PredictionPolicy
from app.services.prediction.provider import (
    PredictionProvider,
    PredictionProviderError,
    PredictionProviderRequest,
    PredictionProviderResult,
)
from app.services.prediction.request import build_prediction_request
from app.services.prediction.runtime import PredictionAttemptInput


class PredictionProviderExecutor:
    """Composes one runtime attempt into one bounded provider request."""

    def __init__(
        self,
        *,
        provider: PredictionProvider,
        clock: Callable[[], int],
        policy: PredictionPolicy | None = None,
        max_candidates: int = 3,
        max_output_tokens: int = 512,
    ) -> None:
        if not 1 <= max_candidates <= MAX_PREDICTION_CANDIDATES:
            raise ValueError("prediction executor candidate bound is invalid")
        if not 1 <= max_output_tokens <= MAX_PREDICTION_OUTPUT_TOKENS:
            raise ValueError("prediction executor output token bound is invalid")
        self._provider = provider
        self._clock = clock
        self._policy = policy or LikelyNextTurnPolicy()
        self._max_candidates = max_candidates
        self._max_output_tokens = max_output_tokens

    async def execute(
        self,
        attempt: PredictionAttemptInput,
    ) -> PredictionProviderResult:
        requested_ms = max(self._clock(), attempt.observed_ms)
        request = build_prediction_request(
            attempt.active_turn,
            attempt.triggering_utterance,
            attempt.context,
            input_revision=attempt.input_revision,
            attempt=attempt.attempt,
            requested_ms=requested_ms,
            input_observed_ms=attempt.observed_ms,
        )
        if request.material_fingerprint != attempt.material_fingerprint:
            raise PredictionProviderError(
                PredictionFailureCategory.CONFIGURATION,
                "Prediction request provenance is inconsistent.",
                retryable=False,
            )
        provider_request = PredictionProviderRequest(
            prediction_id=request.prediction_id,
            input_revision=request.input_revision,
            attempt=request.attempt,
            prompt=self._policy.build_prompt(request),
            max_candidates=self._max_candidates,
            max_output_tokens=self._max_output_tokens,
        )
        result = await self._provider.predict(provider_request)
        if not isinstance(result, PredictionProviderResult):
            raise PredictionProviderError(
                PredictionFailureCategory.MALFORMED_OUTPUT,
                "Prediction provider returned invalid output.",
                retryable=False,
            )
        if len(result.candidates) > provider_request.max_candidates:
            raise PredictionProviderError(
                PredictionFailureCategory.MALFORMED_OUTPUT,
                "Prediction provider exceeded the candidate limit.",
                retryable=False,
            )
        return result
