"""Run one sanitized minimal Gemini Interactions diagnostic request."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from google import genai

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_4_PROVIDER_DIAGNOSTIC.json"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402


def _json_body(exc: BaseException) -> dict[str, Any]:
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        with suppress(ValueError, TypeError):
            body = json.loads(body)
    return body if isinstance(body, dict) else {}


def _redact(text: object, *, api_key: str) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    safe = text.replace(api_key, "[REDACTED_API_KEY]")
    safe = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", safe)
    safe = re.sub(
        r"(?i)(?:api[_ -]?key|x-goog-api-key)(\s*[:=]\s*)[^\s,;\"']+",
        r"api_key\1[REDACTED]",
        safe,
    )
    safe = " ".join(safe.split())
    return safe[:700]


def _sanitized_error(exc: BaseException, *, api_key: str) -> dict[str, object]:
    body = _json_body(exc)
    provider_error = body.get("error")
    if not isinstance(provider_error, dict):
        provider_error = body
    message = provider_error.get("message")
    if not isinstance(message, str):
        message = getattr(exc, "message", None)
    provider_code = provider_error.get("code")
    return {
        "exception_type": type(exc).__name__,
        "provider_http_status": getattr(exc, "status_code", None),
        "provider_code": _redact(provider_code, api_key=api_key),
        "provider_message": _redact(message, api_key=api_key),
    }


async def main() -> int:
    settings = Settings(_env_file=BACKEND_ROOT / ".env")
    api_key = settings.gemini_key
    if api_key is None:
        print("Gemini is not configured. Run configure-gemini.bat first.")
        return 2

    started_ns = perf_counter_ns()
    client = None
    text_seen = False
    completed = False
    error: dict[str, object] | None = None
    try:
        client = genai.Client(
            api_key=api_key,
            http_options={"retry_options": {"attempts": 0}},
        )
        interaction = await client.aio.interactions.create(
            model="gemini-3.8-flash",
            input=[
                {
                    "type": "user_input",
                    "content": [
                        {"type": "text", "text": "Reply with the single word OK."}
                    ],
                }
            ],
            store=False,
        )
        text_seen = bool(getattr(interaction, "output_text", "").strip())
        completed = getattr(interaction, "status", None) == "completed"
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
            raise
        error = _sanitized_error(exc, api_key=api_key)
    finally:
        if client is not None:
            with suppress(Exception):
                await client.aio.aclose()

    result = {
        "schema_version": 2,
        "created_utc": datetime.now(UTC).isoformat(),
        "api": "Gemini Interactions API",
        "request_profile": "minimal_direct_sdk_stateless_nonstreaming",
        "model": "gemini-3.8-flash",
        "store": False,
        "stream": False,
        "system_instruction": False,
        "generation_config": False,
        "tools": False,
        "request_count": 1,
        "configured_key_suffix": f"...{api_key[-4:]}",
        "text_seen": text_seen,
        "completed": completed,
        "elapsed_ms": round((perf_counter_ns() - started_ns) / 1_000_000),
        "error": error,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized diagnostic written to {RESULT_PATH}")
    print(f"Configured key suffix: ...{api_key[-4:]}")
    if error is None:
        print(
            "Diagnostic succeeded: "
            f"completed={completed}, text_seen={text_seen}."
        )
        return 0 if completed and text_seen else 1

    print(
        "Diagnostic result: "
        f"http={error['provider_http_status']}, "
        f"code={error['provider_code']}, "
        f"message={error['provider_message']}"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
