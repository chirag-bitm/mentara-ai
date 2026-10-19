from pydantic import SecretStr

from app.core.config import Settings
import pytest

from app.services.stt.base import STTProviderConfigurationError
from app.services.stt.factory import (
    create_resilient_stt_provider,
    create_stt_provider,
)
from app.services.stt.gemini import GeminiTranscribeProvider
from app.services.stt.rotation import RotatingSTTProvider
from app.services.prediction import (
    EventLoopIsolatedPredictionProvider,
    create_prediction_provider,
)


def test_gemini_is_default_provider() -> None:
    settings = Settings(_env_file=None)
    assert settings.stt_provider == "gemini"
    assert settings.gemini_model == "gemini-3.5-transcribe-live"
    assert settings.stt_configured is False
    assert settings.answer_generation_enabled is True
    assert settings.answer_provider == "gemini"
    assert settings.gemini_answer_model == "gemini-3.5-flash-lite"
    assert settings.gemini_answer_thinking_level == "minimal"
    assert settings.answer_max_output_tokens == 512
    assert settings.answer_configured is False
    assert settings.memory_context_enabled is True
    assert settings.memory_max_retained_turns == 256
    assert settings.memory_max_retained_text_chars == 160_000
    assert settings.memory_max_turn_chars == 4_000
    assert settings.memory_context_recent_turns == 4
    assert settings.memory_context_relevant_turns == 4
    assert settings.prediction_enabled is True
    assert settings.prediction_provider == "gemini"
    assert settings.gemini_prediction_model == "gemini-3.5-flash-lite"
    assert settings.gemini_prediction_thinking_level == "minimal"
    assert settings.prediction_min_active_chars == 12
    assert settings.prediction_min_lexical_tokens == 3
    assert settings.prediction_long_partial_chars == 48
    assert settings.prediction_coalesce_ms == 350
    assert settings.prediction_min_call_interval_ms == 1_200
    assert settings.prediction_cancelled_attempt_cooldown_ms == 4_000
    assert settings.prediction_max_compatible_extension_chars == 96
    assert settings.prediction_max_attempts_per_turn == 2
    assert settings.prediction_max_calls_per_session == 64
    assert settings.prediction_provider_timeout_seconds == 5.0
    assert settings.prediction_max_candidates == 3
    assert settings.prediction_max_output_tokens == 512
    assert settings.prediction_context_recent_turns == 2
    assert settings.prediction_context_relevant_turns == 2
    assert settings.prediction_context_max_total_chars == 3_200
    assert settings.prediction_context_max_active_chars == 1_200
    assert settings.prediction_context_max_memory_turn_chars == 800


def test_gemini_key_configures_stt_and_answer_generation() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
    )
    assert settings.stt_configured is True
    assert settings.answer_configured is True
    assert settings.prediction_configured is True


def test_answer_feature_flag_is_one_clean_rollback_boundary() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        answer_generation_enabled=False,
    )
    assert settings.stt_configured is True
    assert settings.answer_configured is False


def test_memory_feature_flag_is_independent_of_answer_and_conversation_flags() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        memory_context_enabled=False,
    )
    assert settings.memory_context_enabled is False
    assert settings.answer_configured is True
    assert settings.conversation_analysis_enabled is True


def test_prediction_feature_flag_is_independent_and_defaults_on() -> None:
    enabled = Settings(_env_file=None)
    disabled = Settings(_env_file=None, prediction_enabled=False)

    assert enabled.prediction_enabled is True
    assert disabled.prediction_enabled is False
    assert disabled.memory_context_enabled is True
    assert disabled.answer_generation_enabled is True
    assert disabled.conversation_analysis_enabled is True
    assert disabled.prediction_configured is False


def test_gemini_prediction_provider_factory() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
    )

    provider = create_prediction_provider(settings)

    assert isinstance(provider, EventLoopIsolatedPredictionProvider)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"prediction_min_active_chars": 50, "prediction_long_partial_chars": 49},
            "PREDICTION_LONG_PARTIAL_CHARS",
        ),
        (
            {
                "prediction_max_attempts_per_turn": 3,
                "prediction_max_calls_per_session": 2,
            },
            "PREDICTION_MAX_CALLS_PER_SESSION",
        ),
        (
            {
                "prediction_context_max_total_chars": 100,
                "prediction_context_max_active_chars": 101,
            },
            "PREDICTION_CONTEXT_MAX_ACTIVE_CHARS",
        ),
        (
            {
                "prediction_context_max_total_chars": 1_200,
                "prediction_context_max_memory_turn_chars": 1_201,
            },
            "PREDICTION_CONTEXT_MAX_MEMORY_TURN_CHARS",
        ),
    ],
)
def test_prediction_cross_field_limits_are_validated(
    overrides: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, **overrides)


def test_memory_entry_limit_cannot_exceed_total_storage_limit() -> None:
    with pytest.raises(ValueError, match="MEMORY_MAX_TURN_CHARS"):
        Settings(
            _env_file=None,
            memory_max_retained_text_chars=100,
            memory_max_turn_chars=101,
        )


def test_gemini_provider_factory() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        gemini_language_codes="en-IN,hi-IN",
    )
    provider = create_stt_provider(settings)
    assert isinstance(provider, GeminiTranscribeProvider)
    assert settings.gemini_language_code_list == ["en-IN", "hi-IN"]


def test_gemini_resilient_factory_enables_rotation_by_default() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
    )

    provider = create_resilient_stt_provider(settings)

    assert isinstance(provider, RotatingSTTProvider)


def test_gemini_rotation_can_be_disabled_for_clean_rollback() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        gemini_rotation_enabled=False,
    )

    provider = create_resilient_stt_provider(settings)

    assert isinstance(provider, GeminiTranscribeProvider)


def test_rotation_window_must_end_before_provider_limit() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-key"),
        gemini_rotation_interval_seconds=590,
        gemini_rotation_final_wait_seconds=10,
    )

    with pytest.raises(STTProviderConfigurationError, match="600-second"):
        create_resilient_stt_provider(settings)


def test_gemini_setup_message_matches_live_transcribe_protocol() -> None:
    provider = GeminiTranscribeProvider(
        api_key="test-key",
        model="gemini-3.5-transcribe-live",
        language_codes=[],
        transcription_mode="VERBATIM",
    )
    assert provider._setup_message() == {
        "setup": {
            "model": "models/gemini-3.5-transcribe-live",
            "generationConfig": {"responseModalities": ["TEXT"]},
            "inputAudioTranscription": {
                "languageCodes": [],
                "mode": "VERBATIM",
            },
        }
    }


def test_gemini_error_message_redacts_api_key() -> None:
    provider = GeminiTranscribeProvider(
        api_key="super-secret-key",
        model="gemini-3.5-transcribe-live",
        language_codes=[],
        transcription_mode="VERBATIM",
    )
    message = provider._safe_error_message(
        RuntimeError("failed at ?key=super-secret-key")
    )
    assert "super-secret-key" not in message
    assert "[REDACTED]" in message
