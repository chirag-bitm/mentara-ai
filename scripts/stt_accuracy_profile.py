"""Safely switch only non-secret Gemini settings for the M3 accuracy gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
STATE_PATH = PROJECT_ROOT / "backend" / ".stt-accuracy-state.json"

PROFILES = {
    "A": {"language_codes": "", "transcription_mode": "VERBATIM"},
    "B": {
        "language_codes": "en-IN,hi-IN",
        "transcription_mode": "VERBATIM",
    },
}


def _read_lines() -> list[str]:
    if not ENV_PATH.exists():
        raise SystemExit(
            "backend/.env is missing. Run setup.bat and configure-gemini.bat first."
        )
    return ENV_PATH.read_text(encoding="utf-8").splitlines()


def _read_value(lines: list[str], name: str, default: str) -> str:
    prefix = f"{name}="
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return default


def _safe_config(lines: list[str]) -> dict[str, str]:
    return {
        "language_codes": _read_value(lines, "GEMINI_LANGUAGE_CODES", ""),
        "transcription_mode": _read_value(
            lines,
            "GEMINI_TRANSCRIPTION_MODE",
            "VERBATIM",
        ),
    }


def _replace_value(lines: list[str], name: str, value: str) -> list[str]:
    prefix = f"{name}="
    replacement = f"{name}={value}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(prefix):
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)
    return updated


def _write_config(config: dict[str, str]) -> None:
    lines = _read_lines()
    lines = _replace_value(
        lines,
        "GEMINI_LANGUAGE_CODES",
        config["language_codes"],
    )
    lines = _replace_value(
        lines,
        "GEMINI_TRANSCRIPTION_MODE",
        config["transcription_mode"],
    )
    temporary = ENV_PATH.with_suffix(".env.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(ENV_PATH)


def _load_saved_current() -> dict[str, str]:
    if not STATE_PATH.exists():
        raise SystemExit("Run 'stt-accuracy.bat begin' before applying a profile.")
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    language_codes = data.get("language_codes")
    transcription_mode = data.get("transcription_mode")
    if not isinstance(language_codes, str) or transcription_mode not in {
        "VERBATIM",
        "SMART",
    }:
        raise SystemExit("The saved accuracy-test state is invalid.")
    return {
        "language_codes": language_codes,
        "transcription_mode": transcription_mode,
    }


def _print_config(label: str, config: dict[str, str]) -> None:
    languages = config["language_codes"] or "<automatic detection>"
    print(label)
    print(f"GEMINI_LANGUAGE_CODES={languages}")
    print(f"GEMINI_TRANSCRIPTION_MODE={config['transcription_mode']}")
    print("No API key or other secret was read or printed.")


def begin() -> None:
    current = _safe_config(_read_lines())
    if not STATE_PATH.exists():
        STATE_PATH.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        _print_config("Saved the original safe settings as profile C:", current)
        return
    _print_config("Profile C was already saved as:", _load_saved_current())


def apply_profile(profile: str) -> None:
    saved_current = _load_saved_current()
    config = saved_current if profile == "C" else PROFILES[profile]
    _write_config(config)
    _print_config(f"Applied profile {profile}:", config)
    print("Restart the backend before testing this profile.")


def status() -> None:
    _print_config("Current effective safe settings:", _safe_config(_read_lines()))
    if STATE_PATH.exists():
        _print_config("Saved original profile C:", _load_saved_current())
    else:
        print("No accuracy comparison is currently in progress.")


def finish() -> None:
    saved_current = _load_saved_current()
    _write_config(saved_current)
    STATE_PATH.unlink()
    _print_config("Restored the original profile C settings:", saved_current)
    print("Restart the backend to use the restored settings.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage safe Gemini STT profiles for the M3 accuracy gate."
    )
    parser.add_argument(
        "command",
        choices=("begin", "A", "B", "C", "status", "finish"),
    )
    args = parser.parse_args()

    if args.command == "begin":
        begin()
    elif args.command in PROFILES or args.command == "C":
        apply_profile(args.command)
    elif args.command == "status":
        status()
    else:
        finish()


if __name__ == "__main__":
    main()
