from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mentara AI API"
    app_env: str = "development"
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:3000"

    stt_provider: Literal["gemini", "deepgram", "local_whisper"] = "gemini"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-transcribe-live"
    gemini_language_codes: str = ""
    gemini_transcription_mode: Literal["VERBATIM", "SMART"] = "VERBATIM"
    gemini_rotation_enabled: bool = True
    gemini_rotation_interval_seconds: float = 540.0
    gemini_rotation_final_wait_seconds: float = 10.0
    gemini_rotation_buffer_chunks: int = 20
    gemini_rotation_max_attempts: int = 3
    gemini_rotation_retry_base_seconds: float = 0.25

    conversation_analysis_enabled: bool = True
    conversation_turn_merge_window_ms: int = Field(default=250, ge=0, le=2_000)

    memory_context_enabled: bool = True
    memory_max_retained_turns: int = Field(default=256, ge=1, le=10_000)
    memory_max_retained_text_chars: int = Field(
        default=160_000,
        ge=100,
        le=5_000_000,
    )
    memory_max_turn_chars: int = Field(default=4_000, ge=50, le=100_000)
    memory_context_recent_turns: int = Field(default=4, ge=0, le=20)
    memory_context_relevant_turns: int = Field(default=4, ge=0, le=20)

    prediction_enabled: bool = True
    prediction_provider: str = "gemini"
    gemini_prediction_model: str = "gemini-3.5-flash-lite"
    gemini_prediction_thinking_level: Literal[
        "minimal", "low", "medium", "high"
    ] = "minimal"
    prediction_min_active_chars: int = Field(default=12, ge=1, le=500)
    prediction_min_lexical_tokens: int = Field(default=3, ge=1, le=50)
    prediction_long_partial_chars: int = Field(default=48, ge=1, le=2_000)
    prediction_coalesce_ms: int = Field(default=350, ge=0, le=5_000)
    prediction_min_call_interval_ms: int = Field(default=1_200, ge=0, le=30_000)
    prediction_cancelled_attempt_cooldown_ms: int = Field(
        default=4_000, ge=0, le=30_000
    )
    prediction_max_compatible_extension_chars: int = Field(
        default=96, ge=0, le=512
    )
    prediction_max_attempts_per_turn: int = Field(default=2, ge=1, le=10)
    prediction_max_calls_per_session: int = Field(default=64, ge=1, le=1_000)
    prediction_provider_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    prediction_max_candidates: int = Field(default=3, ge=1, le=5)
    prediction_max_output_tokens: int = Field(default=512, ge=16, le=512)
    prediction_context_recent_turns: int = Field(default=2, ge=0, le=10)
    prediction_context_relevant_turns: int = Field(default=2, ge=0, le=10)
    prediction_context_max_total_chars: int = Field(
        default=3_200,
        ge=100,
        le=6_000,
    )
    prediction_context_max_active_chars: int = Field(
        default=1_200,
        ge=50,
        le=4_000,
    )
    prediction_context_max_memory_turn_chars: int = Field(
        default=800,
        ge=50,
        le=4_000,
    )

    answer_generation_enabled: bool = True
    answer_provider: str = "gemini"
    gemini_answer_model: str = "gemini-3.5-flash-lite"
    gemini_answer_thinking_level: Literal[
        "minimal", "low", "medium", "high"
    ] = "minimal"
    answer_max_output_tokens: int = Field(default=512, ge=32, le=4_096)
    answer_generation_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    answer_context_recent_turns: int = Field(default=2, ge=0, le=10)
    answer_context_max_total_chars: int = Field(default=6_000, ge=100, le=50_000)
    answer_context_max_turn_chars: int = Field(default=2_000, ge=50, le=20_000)
    answer_outbound_buffer_items: int = Field(default=128, ge=8, le=1_024)
    answer_delta_max_coalesced_chars: int = Field(default=4_096, ge=64, le=32_768)

    deepgram_api_key: SecretStr | None = None
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_memory_bounds(self) -> Self:
        if self.memory_max_turn_chars > self.memory_max_retained_text_chars:
            raise ValueError(
                "MEMORY_MAX_TURN_CHARS cannot exceed "
                "MEMORY_MAX_RETAINED_TEXT_CHARS"
            )
        if self.prediction_long_partial_chars < self.prediction_min_active_chars:
            raise ValueError(
                "PREDICTION_LONG_PARTIAL_CHARS cannot be below "
                "PREDICTION_MIN_ACTIVE_CHARS"
            )
        if (
            self.prediction_max_calls_per_session
            < self.prediction_max_attempts_per_turn
        ):
            raise ValueError(
                "PREDICTION_MAX_CALLS_PER_SESSION cannot be below "
                "PREDICTION_MAX_ATTEMPTS_PER_TURN"
            )
        for value, name in (
            (
                self.prediction_context_max_active_chars,
                "PREDICTION_CONTEXT_MAX_ACTIVE_CHARS",
            ),
            (
                self.prediction_context_max_memory_turn_chars,
                "PREDICTION_CONTEXT_MAX_MEMORY_TURN_CHARS",
            ),
        ):
            if value > self.prediction_context_max_total_chars:
                raise ValueError(
                    f"{name} cannot exceed PREDICTION_CONTEXT_MAX_TOTAL_CHARS"
                )
        return self

    @staticmethod
    def _usable_secret(secret: SecretStr | None, placeholder: str) -> str | None:
        if secret is None:
            return None
        value = secret.get_secret_value().strip()
        return value if value and value != placeholder else None

    @property
    def gemini_key(self) -> str | None:
        return self._usable_secret(
            self.gemini_api_key,
            "replace_with_your_gemini_api_key",
        )

    @property
    def gemini_language_code_list(self) -> list[str]:
        return [
            language.strip()
            for language in self.gemini_language_codes.split(",")
            if language.strip()
        ]

    @property
    def deepgram_key(self) -> str | None:
        return self._usable_secret(
            self.deepgram_api_key,
            "replace_with_your_deepgram_api_key",
        )

    @property
    def stt_configured(self) -> bool:
        if self.stt_provider == "gemini":
            return self.gemini_key is not None
        if self.stt_provider == "deepgram":
            return self.deepgram_key is not None
        return False

    @property
    def stt_model(self) -> str:
        if self.stt_provider == "gemini":
            return self.gemini_model
        if self.stt_provider == "deepgram":
            return self.deepgram_model
        return "not-implemented"

    @property
    def answer_configured(self) -> bool:
        if not self.answer_generation_enabled:
            return False
        if self.answer_provider == "gemini":
            return self.gemini_key is not None
        return False

    @property
    def prediction_configured(self) -> bool:
        if not self.prediction_enabled:
            return False
        if self.prediction_provider == "gemini":
            return self.gemini_key is not None
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
