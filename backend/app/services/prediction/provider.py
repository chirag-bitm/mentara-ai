import asyncio
from concurrent.futures import Future
from contextlib import suppress
from dataclasses import dataclass
import re
import threading
from typing import Protocol
from uuid import UUID

from app.services.prediction.models import (
    MAX_PREDICTION_CANDIDATES,
    MAX_PREDICTION_OUTPUT_TOKENS,
    PredictionCandidate,
    PredictionFailureCategory,
    PredictionPrompt,
    PredictionUsage,
)


@dataclass(slots=True, frozen=True)
class PredictionProviderRequest:
    prediction_id: UUID
    input_revision: int
    attempt: int
    prompt: PredictionPrompt
    max_candidates: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if self.input_revision < 1 or self.attempt < 1:
            raise ValueError("prediction provider revision/attempt must be positive")
        if not 1 <= self.max_candidates <= MAX_PREDICTION_CANDIDATES:
            raise ValueError("prediction provider candidate bound is invalid")
        if not 1 <= self.max_output_tokens <= MAX_PREDICTION_OUTPUT_TOKENS:
            raise ValueError("prediction provider output token bound is invalid")


@dataclass(slots=True, frozen=True)
class PredictionProviderResult:
    candidates: tuple[PredictionCandidate, ...]
    usage: PredictionUsage | None = None
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple):
            raise ValueError("prediction provider candidates must be a tuple")
        if len(self.candidates) > MAX_PREDICTION_CANDIDATES:
            raise ValueError("prediction provider returned too many candidates")
        if any(
            not isinstance(candidate, PredictionCandidate)
            for candidate in self.candidates
        ):
            raise ValueError("prediction provider candidate type is invalid")
        keys = tuple(
            (candidate.kind, candidate.text.casefold()) for candidate in self.candidates
        )
        if len(set(keys)) != len(keys):
            raise ValueError("prediction provider candidates must be unique")
        if self.finish_reason is not None and not self.finish_reason.strip():
            raise ValueError("prediction finish reason must be omitted or non-empty")


class PredictionProvider(Protocol):
    """Provider-neutral one-shot prediction boundary for fake/real adapters."""

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult: ...


class EventLoopIsolatedPredictionProvider:
    """Run one optional provider call outside the realtime application loop.

    Some third-party async SDK paths can still perform synchronous setup,
    serialization, transport or teardown work around their awaited network
    operation. Prediction is advisory, so none of that work may delay the STT
    sender/receiver, canonical transcript processing or answer runtime.

    A fresh daemon worker is used for each call. The runtime already guarantees
    at most one active prediction call per logical turn/session runtime. Outer
    cancellation is forwarded to the worker's asyncio task, so the wrapped
    provider still closes its request promptly and no retry or hidden queue is
    introduced.
    """

    def __init__(
        self,
        provider: PredictionProvider,
        *,
        worker_start_timeout_seconds: float = 2.0,
        worker_cancel_timeout_seconds: float = 2.0,
    ) -> None:
        if worker_start_timeout_seconds <= 0:
            raise ValueError("prediction worker start timeout must be positive")
        if worker_cancel_timeout_seconds <= 0:
            raise ValueError("prediction worker cancel timeout must be positive")
        self._provider = provider
        self._worker_start_timeout_seconds = worker_start_timeout_seconds
        self._worker_cancel_timeout_seconds = worker_cancel_timeout_seconds

    async def predict(
        self,
        request: PredictionProviderRequest,
    ) -> PredictionProviderResult:
        ready = threading.Event()
        done = threading.Event()
        cancel_requested = threading.Event()
        outcome: Future[PredictionProviderResult] = Future()
        worker_state: dict[str, object] = {}

        def run_worker() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            task = loop.create_task(self._provider.predict(request))
            worker_state["loop"] = loop
            worker_state["task"] = task
            ready.set()
            if cancel_requested.is_set():
                task.cancel()
            try:
                result = loop.run_until_complete(task)
            except asyncio.CancelledError:
                outcome.cancel()
            except BaseException as exc:
                if not outcome.done():
                    outcome.set_exception(exc)
            else:
                if not outcome.done():
                    outcome.set_result(result)
            finally:
                pending = tuple(
                    pending_task
                    for pending_task in asyncio.all_tasks(loop)
                    if not pending_task.done()
                )
                for pending_task in pending:
                    pending_task.cancel()
                if pending:
                    with suppress(BaseException):
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                asyncio.set_event_loop(None)
                loop.close()
                done.set()

        worker = threading.Thread(
            target=run_worker,
            name="mentara-prediction-provider",
            daemon=True,
        )
        worker.start()

        try:
            started = await asyncio.to_thread(
                ready.wait,
                self._worker_start_timeout_seconds,
            )
            if not started:
                cancel_requested.set()
                raise PredictionProviderError(
                    PredictionFailureCategory.TIMEOUT,
                    "Prediction worker did not start in time.",
                    retryable=True,
                )
            return await asyncio.wrap_future(outcome)
        except asyncio.CancelledError:
            cancel_requested.set()
            self._cancel_worker(worker_state)
            raise
        finally:
            if cancel_requested.is_set():
                self._cancel_worker(worker_state)
            stopped = await asyncio.to_thread(
                done.wait,
                self._worker_cancel_timeout_seconds,
            )
            if stopped:
                worker.join(timeout=0)

    @staticmethod
    def _cancel_worker(worker_state: dict[str, object]) -> None:
        loop = worker_state.get("loop")
        task = worker_state.get("task")
        if not isinstance(loop, asyncio.AbstractEventLoop):
            return
        if not isinstance(task, asyncio.Task):
            return
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(task.cancel)


class PredictionProviderError(Exception):
    def __init__(
        self,
        category: PredictionFailureCategory,
        safe_message: str,
        *,
        retryable: bool,
        provider_status_code: int | None = None,
        provider_error_status: str | None = None,
        provider_reason: str | None = None,
    ) -> None:
        if not safe_message.strip():
            raise ValueError("safe prediction provider message must not be empty")
        if provider_status_code is not None and not 100 <= provider_status_code <= 599:
            raise ValueError("provider status code must be a valid HTTP status")
        for value, label in (
            (provider_error_status, "provider error status"),
            (provider_reason, "provider reason"),
        ):
            if (
                value is not None
                and re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", value) is None
            ):
                raise ValueError(f"{label} must be a safe identifier")
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.retryable = retryable
        self.provider_status_code = provider_status_code
        self.provider_error_status = provider_error_status
        self.provider_reason = provider_reason
