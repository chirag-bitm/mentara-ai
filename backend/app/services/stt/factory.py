from app.core.config import Settings
from app.services.stt.base import STTProvider, STTProviderConfigurationError
from app.services.stt.deepgram import DeepgramProvider
from app.services.stt.gemini import GeminiTranscribeProvider
from app.services.stt.rotation import (
    LifecycleCallback,
    RotatingSTTProvider,
    RotationPolicy,
)


def create_stt_provider(settings: Settings) -> STTProvider:
    """Build the selected adapter without leaking provider details into the API route."""

    if settings.stt_provider == "gemini":
        if settings.gemini_key is None:
            raise STTProviderConfigurationError(
                "GEMINI_API_KEY is missing in backend/.env."
            )
        return GeminiTranscribeProvider(
            api_key=settings.gemini_key,
            model=settings.gemini_model,
            language_codes=settings.gemini_language_code_list,
            transcription_mode=settings.gemini_transcription_mode,
        )

    if settings.stt_provider == "deepgram":
        if settings.deepgram_key is None:
            raise STTProviderConfigurationError(
                "DEEPGRAM_API_KEY is missing in backend/.env."
            )
        return DeepgramProvider(
            api_key=settings.deepgram_key,
            model=settings.deepgram_model,
            language=settings.deepgram_language,
        )

    raise STTProviderConfigurationError(
        "LocalWhisperProvider is reserved for a future free mode and is not implemented."
    )


def create_resilient_stt_provider(
    settings: Settings,
    *,
    lifecycle_callback: LifecycleCallback | None = None,
) -> STTProvider:
    """Add controlled rotation without changing the provider-neutral contract."""

    initial_provider = create_stt_provider(settings)
    if settings.stt_provider != "gemini" or not settings.gemini_rotation_enabled:
        return initial_provider

    if (
        settings.gemini_rotation_interval_seconds
        + settings.gemini_rotation_final_wait_seconds
        >= 600
    ):
        raise STTProviderConfigurationError(
            "Gemini rotation interval plus final-boundary wait must stay below "
            "the 600-second provider-session limit."
        )

    try:
        policy = RotationPolicy(
            rotation_interval_seconds=settings.gemini_rotation_interval_seconds,
            final_boundary_wait_seconds=settings.gemini_rotation_final_wait_seconds,
            audio_buffer_max_chunks=settings.gemini_rotation_buffer_chunks,
            reconnect_max_attempts=settings.gemini_rotation_max_attempts,
            reconnect_base_delay_seconds=settings.gemini_rotation_retry_base_seconds,
        )
    except ValueError as exc:
        raise STTProviderConfigurationError(
            f"Invalid Gemini rotation settings: {exc}"
        ) from exc
    return RotatingSTTProvider(
        initial_provider=initial_provider,
        provider_factory=lambda: create_stt_provider(settings),
        policy=policy,
        lifecycle_callback=lifecycle_callback,
    )
