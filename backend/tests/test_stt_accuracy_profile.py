import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "stt_accuracy_profile.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("stt_accuracy_profile", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profiles_preserve_secret_and_restore_original_safe_settings(
    tmp_path,
    capsys,
) -> None:
    helper = load_helper()
    env_path = tmp_path / ".env"
    state_path = tmp_path / ".stt-accuracy-state.json"
    secret = "private-test-value"
    env_path.write_text(
        "\n".join(
            (
                "APP_ENV=development",
                f"GEMINI_API_KEY={secret}",
                "GEMINI_LANGUAGE_CODES=en-US",
                "GEMINI_TRANSCRIPTION_MODE=SMART",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    helper.ENV_PATH = env_path
    helper.STATE_PATH = state_path

    helper.begin()
    assert state_path.exists()
    assert secret not in state_path.read_text(encoding="utf-8")

    helper.apply_profile("A")
    profile_a = env_path.read_text(encoding="utf-8")
    assert "GEMINI_LANGUAGE_CODES=\n" in profile_a
    assert "GEMINI_TRANSCRIPTION_MODE=VERBATIM" in profile_a
    assert f"GEMINI_API_KEY={secret}" in profile_a

    helper.apply_profile("B")
    profile_b = env_path.read_text(encoding="utf-8")
    assert "GEMINI_LANGUAGE_CODES=en-IN,hi-IN" in profile_b
    assert f"GEMINI_API_KEY={secret}" in profile_b

    helper.apply_profile("C")
    restored_c = env_path.read_text(encoding="utf-8")
    assert "GEMINI_LANGUAGE_CODES=en-US" in restored_c
    assert "GEMINI_TRANSCRIPTION_MODE=SMART" in restored_c

    helper.finish()
    assert not state_path.exists()
    assert env_path.read_text(encoding="utf-8") == restored_c
    assert secret not in capsys.readouterr().out


def test_begin_is_idempotent_and_does_not_overwrite_saved_profile(tmp_path) -> None:
    helper = load_helper()
    env_path = tmp_path / ".env"
    state_path = tmp_path / ".stt-accuracy-state.json"
    env_path.write_text(
        "GEMINI_LANGUAGE_CODES=\nGEMINI_TRANSCRIPTION_MODE=VERBATIM\n",
        encoding="utf-8",
    )
    helper.ENV_PATH = env_path
    helper.STATE_PATH = state_path

    helper.begin()
    original_state = state_path.read_text(encoding="utf-8")
    helper.apply_profile("B")
    helper.begin()

    assert state_path.read_text(encoding="utf-8") == original_state
