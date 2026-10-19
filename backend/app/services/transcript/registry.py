from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from app.services.transcript.session import (
    SessionConnectionState,
    TranscriptionSession,
)

if TYPE_CHECKING:
    from app.services.prediction.models import PredictionInvalidationReason


class SessionResumeUnavailableError(LookupError):
    """Raised when a resume token is unknown or its grace period has expired."""


class SessionAlreadyAttachedError(RuntimeError):
    """Raised when another browser connection still owns the logical session."""


@dataclass(slots=True, frozen=True)
class TranscriptionSessionLease:
    resume_token: str
    lease_id: UUID
    session: TranscriptionSession
    resume_ttl_seconds: float


class TranscriptionSessionRegistry(Protocol):
    """Replaceable storage boundary for resumable logical sessions."""

    def create(self, session: TranscriptionSession) -> TranscriptionSessionLease: ...

    def attach(self, resume_token: str) -> TranscriptionSessionLease: ...

    def detach(self, lease: TranscriptionSessionLease) -> bool: ...

    def remove(self, lease: TranscriptionSessionLease) -> bool: ...

    async def shutdown(self) -> None: ...


@dataclass(slots=True)
class _RegistryEntry:
    session: TranscriptionSession
    lease_id: UUID
    expires_at: float | None = None
    expiry_handle: asyncio.TimerHandle | None = None


class InMemoryTranscriptionSessionRegistry:
    """Single-process session registry with exclusive leases and bounded expiry."""

    def __init__(
        self,
        *,
        resume_ttl_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] | None = None,
        lease_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        if resume_ttl_seconds <= 0:
            raise ValueError("resume_ttl_seconds must be positive")

        self._resume_ttl_seconds = resume_ttl_seconds
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._lease_id_factory = lease_id_factory
        self._entries: dict[str, _RegistryEntry] = {}
        self._lock = RLock()

    @property
    def resume_ttl_seconds(self) -> float:
        return self._resume_ttl_seconds

    @property
    def size(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._entries)

    def create(self, session: TranscriptionSession) -> TranscriptionSessionLease:
        with self._lock:
            self._purge_expired_locked()
            token = self._new_unique_token_locked()
            lease_id = self._lease_id_factory()
            self._entries[token] = _RegistryEntry(
                session=session,
                lease_id=lease_id,
            )
            return self._lease(token, self._entries[token])

    def attach(self, resume_token: str) -> TranscriptionSessionLease:
        with self._lock:
            self._purge_expired_locked()
            entry = self._entries.get(resume_token)
            if entry is None:
                raise SessionResumeUnavailableError(
                    "The previous transcription session is no longer available."
                )
            if entry.expires_at is None:
                raise SessionAlreadyAttachedError(
                    "The previous browser connection is still releasing the session."
                )

            if entry.expiry_handle is not None:
                entry.expiry_handle.cancel()
                entry.expiry_handle = None
            entry.expires_at = None
            entry.lease_id = self._lease_id_factory()
            return self._lease(resume_token, entry)

    def detach(self, lease: TranscriptionSessionLease) -> bool:
        with self._lock:
            entry = self._entries.get(lease.resume_token)
            if entry is None or entry.lease_id != lease.lease_id:
                return False
            if entry.expires_at is not None:
                return True

            entry.expires_at = self._clock() + self._resume_ttl_seconds
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                entry.expiry_handle = None
            else:
                entry.expiry_handle = loop.call_later(
                    self._resume_ttl_seconds,
                    self._expire,
                    lease.resume_token,
                    lease.lease_id,
                )
            return True

    def remove(self, lease: TranscriptionSessionLease) -> bool:
        from app.services.prediction.models import PredictionInvalidationReason

        with self._lock:
            entry = self._entries.get(lease.resume_token)
            if entry is None or entry.lease_id != lease.lease_id:
                return False
            self._remove_locked(
                lease.resume_token,
                entry,
                prediction_reason=PredictionInvalidationReason.STOP_REQUESTED,
            )
            return True

    def purge_expired(self) -> int:
        with self._lock:
            return self._purge_expired_locked()

    def clear(self) -> None:
        from app.services.prediction.models import PredictionInvalidationReason

        with self._lock:
            for token, entry in tuple(self._entries.items()):
                self._remove_locked(
                    token,
                    entry,
                    prediction_reason=PredictionInvalidationReason.BACKEND_SHUTDOWN,
                )

    async def shutdown(self) -> None:
        """Cancel every logical session and await its asynchronous side-car work."""

        from app.services.prediction.models import PredictionInvalidationReason

        with self._lock:
            answer_runtimes = tuple(
                entry.session.answer_runtime
                for entry in self._entries.values()
                if entry.session.answer_runtime is not None
            )
            prediction_runtimes = tuple(
                entry.session.prediction_runtime
                for entry in self._entries.values()
                if entry.session.prediction_runtime is not None
            )
            for token, entry in tuple(self._entries.items()):
                self._remove_locked(
                    token,
                    entry,
                    prediction_reason=PredictionInvalidationReason.BACKEND_SHUTDOWN,
                )
        if answer_runtimes:
            await asyncio.gather(
                *(runtime.wait_idle() for runtime in answer_runtimes),
                return_exceptions=True,
            )
        if prediction_runtimes:
            await asyncio.gather(
                *(runtime.wait_idle() for runtime in prediction_runtimes),
                return_exceptions=True,
            )

    def _new_unique_token_locked(self) -> str:
        for _ in range(10):
            token = self._token_factory()
            if token and token not in self._entries:
                return token
        raise RuntimeError("Could not create a unique session resume token.")

    def _lease(
        self,
        resume_token: str,
        entry: _RegistryEntry,
    ) -> TranscriptionSessionLease:
        return TranscriptionSessionLease(
            resume_token=resume_token,
            lease_id=entry.lease_id,
            session=entry.session,
            resume_ttl_seconds=self._resume_ttl_seconds,
        )

    def _expire(self, resume_token: str, lease_id: UUID) -> None:
        from app.services.prediction.models import PredictionInvalidationReason

        with self._lock:
            entry = self._entries.get(resume_token)
            if (
                entry is None
                or entry.lease_id != lease_id
                or entry.expires_at is None
            ):
                return
            remaining_seconds = entry.expires_at - self._clock()
            if remaining_seconds > 0:
                # Event loops may invoke timers up to one clock-resolution
                # early. Keep the lease bounded by rescheduling instead of
                # dropping its only expiry callback.
                loop = asyncio.get_running_loop()
                entry.expiry_handle = loop.call_later(
                    max(remaining_seconds, 0.001),
                    self._expire,
                    resume_token,
                    lease_id,
                )
                return
            self._remove_locked(
                resume_token,
                entry,
                prediction_reason=PredictionInvalidationReason.SESSION_EXPIRED,
            )

    def _purge_expired_locked(self) -> int:
        from app.services.prediction.models import PredictionInvalidationReason

        now = self._clock()
        expired = [
            (token, entry)
            for token, entry in self._entries.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for token, entry in expired:
            self._remove_locked(
                token,
                entry,
                prediction_reason=PredictionInvalidationReason.SESSION_EXPIRED,
            )
        return len(expired)

    def _remove_locked(
        self,
        resume_token: str,
        entry: _RegistryEntry,
        *,
        prediction_reason: PredictionInvalidationReason,
    ) -> None:
        if entry.expiry_handle is not None:
            entry.expiry_handle.cancel()
        self._entries.pop(resume_token, None)
        entry.session.shutdown_prediction(prediction_reason)
        if entry.session.connection_state is not SessionConnectionState.STOPPED:
            entry.session.transition(SessionConnectionState.STOPPED)
