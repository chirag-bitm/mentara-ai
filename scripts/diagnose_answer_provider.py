"""Run one sanitized, stateless Gemini Interactions diagnostic request."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
RESULT_PATH = PROJECT_ROOT / "docs" / "MILESTONE_4_PROVIDER_DIAGNOSTIC.json"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.services.answer.gemini import GeminiAnswerProvider  # noqa: E402
from app.services.answer.models import (  # noqa: E402
    AnswerPrompt,
    AnswerProviderCompleted,
    AnswerProviderTextDelta,
)
from app.services.answer.provider import (  # noqa: E402
    AnswerProviderError,
    AnswerProviderRequest,
)


async def main() -> int:
    settings = Settings(_env_file=BACKEND_ROOT / ".env")
    api_key = settings.gemini_key
    if api_key is None:
        print("Gemini is not configured. Run configure-gemini.bat first.")
        return 2

    provider = GeminiAnswerProvider(
        api_key=api_key,
        model="gemini-3.8-flash",
        thinking_level="low",
        max_output_tokens=512,
    )
    request = AnswerProviderRequest(
        answer_id=UUID("50000000-0000-0000-0000-000000000001"),
        attempt=1,
        prompt=AnswerPrompt(
            system_instruction="Reply concisely. Do not use tools.",
            user_content="Reply with the single word OK.",
        ),
    )
    started_ns = perf_counter_ns()
    stream = None
    text_seen = False
    completed = False
    error: dict[str, object] | None = None
    try:
        async with asyncio.timeout(20):
            stream = await provider.start(request)
            async for event in stream:
                if isinstance(event, AnswerProviderTextDelta) and event.text.strip():
                    text_seen = True
                if isinstance(event, AnswerProviderCompleted):
                    completed = True
                    break
    except AnswerProviderError as exc:
        error = {
            "category": exc.category.value,
            "provider_http_status": exc.provider_status_code,
            "provider_error_status": exc.provider_error_status,
            "safe_reason": exc.provider_reason,
        }
    except TimeoutError:
        error = {
            "category": "timeout",
            "provider_http_status": None,
            "provider_error_status": None,
            "safe_reason": "diagnostic_timeout",
        }
    finally:
        if stream is not None:
            with suppress(Exception):
                await stream.aclose()

    result = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "api": "Gemini Interactions API",
        "model": "gemini-3.8-flash",
        "thinking_level": "low",
        "store": False,
        "request_count": 1,
        "text_seen": text_seen,
        "completed": completed,
        "elapsed_ms": round((perf_counter_ns() - started_ns) / 1_000_000),
        "error": error,
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Sanitized diagnostic written to {RESULT_PATH}")
    if error is None:
        print("Diagnostic succeeded.")
    else:
        print(
            "Diagnostic result: "
            f"category={error['category']}, "
            f"http={error['provider_http_status']}, "
            f"status={error['provider_error_status']}, "
            f"reason={error['safe_reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
