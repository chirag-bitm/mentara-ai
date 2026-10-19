from app.core.config import Settings
from app.services.prediction.gemini import GeminiPredictionProvider
from app.services.prediction.models import PredictionFailureCategory
from app.services.prediction.provider import (
    EventLoopIsolatedPredictionProvider,
    PredictionProvider,
    PredictionProviderError,
)


def create_prediction_provider(settings: Settings) -> PredictionProvider:
    if settings.prediction_provider != "gemini":
        raise PredictionProviderError(
            PredictionFailureCategory.CONFIGURATION,
            f"The '{settings.prediction_provider}' prediction provider is not supported.",
            retryable=False,
        )
    api_key = settings.gemini_key
    if api_key is None:
        raise PredictionProviderError(
            PredictionFailureCategory.CONFIGURATION,
            "Gemini prediction is not configured.",
            retryable=False,
        )
    if not settings.gemini_prediction_model.strip():
        raise PredictionProviderError(
            PredictionFailureCategory.CONFIGURATION,
            "A Gemini prediction model is required.",
            retryable=False,
        )
    return EventLoopIsolatedPredictionProvider(
        GeminiPredictionProvider(
            api_key=api_key,
            model=settings.gemini_prediction_model,
            thinking_level=settings.gemini_prediction_thinking_level,
        )
    )

