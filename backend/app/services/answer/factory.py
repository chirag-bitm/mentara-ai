from app.core.config import Settings
from app.services.answer.gemini import GeminiAnswerProvider
from app.services.answer.models import AnswerFailureCategory
from app.services.answer.provider import AnswerProvider, AnswerProviderError


def create_answer_provider(settings: Settings) -> AnswerProvider:
    if settings.answer_provider != "gemini":
        raise AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            f"The '{settings.answer_provider}' answer provider is not supported.",
            retryable=False,
        )
    api_key = settings.gemini_key
    if api_key is None:
        raise AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            "Gemini answer generation is not configured.",
            retryable=False,
        )
    if not settings.gemini_answer_model.strip():
        raise AnswerProviderError(
            AnswerFailureCategory.CONFIGURATION,
            "A Gemini answer model is required.",
            retryable=False,
        )
    return GeminiAnswerProvider(
        api_key=api_key,
        model=settings.gemini_answer_model,
        thinking_level=settings.gemini_answer_thinking_level,
        max_output_tokens=settings.answer_max_output_tokens,
    )
