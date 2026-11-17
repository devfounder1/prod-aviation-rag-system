"""Request-owned cancellation, transport interruption and stale callback guards."""
from __future__ import annotations
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
import threading
from typing import Any
import uuid

logger = logging.getLogger(__name__)


class CancelToken(dict[str, bool]):
    def __init__(self) -> None:
        super().__init__(cancelled=False)
        self._lock = threading.RLock()
        self._closers: list[Callable[[], None]] = []

    def __setitem__(self, key: str, value: bool) -> None:
        callbacks: list[Callable[[], None]] = []
        with self._lock:
            super().__setitem__(key, value)
            if key == 'cancelled' and value:
                callbacks, self._closers = self._closers, []
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.debug('Cancellation transport already closed')

    def on_cancel(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            cancelled = self.get('cancelled')
            if not cancelled:
                self._closers.append(callback)
        if cancelled:
            callback()

        def remove() -> None:
            with self._lock:
                if callback in self._closers:
                    self._closers.remove(callback)
        return remove


current_token: ContextVar[CancelToken | None] = ContextVar('request_cancel_token', default=None)
# Bound expensive work across all chats and model instances in this desktop process.
_inference_slot = threading.Semaphore(1)


@contextmanager
def request_scope(flag: dict[str, bool] | None) -> Iterator[bool]:
    token = flag if isinstance(flag, CancelToken) else None
    context = current_token.set(token)
    acquired = False
    try:
        while not (flag and flag.get('cancelled')):
            if _inference_slot.acquire(timeout=0.1):
                acquired = True
                break
        yield acquired and not bool(flag and flag.get('cancelled'))
    finally:
        if acquired:
            _inference_slot.release()
        current_token.reset(context)


def track_response(response: Any) -> None:
    token = current_token.get()
    if token:
        token.on_cancel(response.close)


async def track_async_response(response: Any) -> None:
    # Async UI uses aquery -> worker thread + synchronous HTTP. This hook is
    # present for compatibility; async HTTP has no cross-thread close callback.
    token = current_token.get()
    if token is not None and token.get('cancelled'):
        await response.aclose()


@dataclass
class RequestJob:
    chat_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    token: CancelToken = field(default_factory=CancelToken)


class JobController:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.current: RequestJob | None = None
        self._closed = False

    def start(self, chat_id: str) -> RequestJob:
        with self._lock:
            if self._closed:
                raise RuntimeError('Application is closed')
            previous = self.current
            self.current = RequestJob(chat_id)
            job = self.current
        if previous:
            previous.token['cancelled'] = True
        return job

    def cancel(self) -> None:
        with self._lock:
            previous, self.current = self.current, None
        if previous:
            previous.token['cancelled'] = True

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self.cancel()

    def is_current(self, job: RequestJob) -> bool:
        with self._lock:
            return not self._closed and self.current is job and not job.token.get('cancelled', False)

    def apply(self, job: RequestJob, action: Callable[[], None]) -> bool:
        """Recheck ownership when a queued callback executes, not when submitted."""
        with self._lock:
            if self.current is not job or job.token.get('cancelled'):
                return False
            action()
            return True

    def finish(self, job: RequestJob) -> None:
        with self._lock:
            if self.current is job:
                self.current = None
