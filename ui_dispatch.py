"""Page-owned scheduling with no coroutine creation after the UI loop shuts down."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class UiDispatcher:
    def __init__(self, page: Any, on_unavailable: Callable[[], None] | None = None) -> None:
        self.page = page
        self._closed = threading.Event()
        self._on_unavailable = on_unavailable
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def active(self) -> bool:
        if self._closed.is_set():
            return False
        if self.page.loop.is_closed() or not self.page.loop.is_running():
            self.close()
            if self._on_unavailable:
                self._on_unavailable()
            return False
        return True

    def close(self) -> None:
        self._closed.set()
        if not self.page.loop.is_closed():
            try:
                self.page.loop.call_soon_threadsafe(self._cancel_tasks)
            except RuntimeError:
                pass

    def _cancel_tasks(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()

    def post(self, action: Callable[..., Any], *args: Any) -> bool:
        if not self.active:
            return False
        def run() -> None:
            if self.active:
                action(*args)
        try:
            self.page.loop.call_soon_threadsafe(run)
            return True
        except RuntimeError:
            if self.page.loop.is_closed():
                self.close()
                if self._on_unavailable:
                    self._on_unavailable()
                return False
            raise

    def run_thread(self, action: Callable[..., Any], *args: Any) -> bool:
        def run() -> None:
            if self.active:
                try:
                    action(*args)
                except RuntimeError:
                    if self.active:
                        raise
        def start() -> None:
            try:
                future = self.page.loop.run_in_executor(self.page.executor, run)
                future.add_done_callback(self._thread_done)
            except RuntimeError as exc:
                if 'shutdown' not in str(exc).lower() and not self.page.loop.is_closed():
                    raise
                self.close()
                if self._on_unavailable:
                    self._on_unavailable()
        return self.post(start)

    def _thread_done(self, future: asyncio.Future[Any]) -> None:
        if not future.cancelled():
            error = future.exception()
            if error and not self._closed.is_set():
                logger.error('UI worker failed: %s', type(error).__name__, exc_info=error)

    def run_task(self, handler: Callable[..., Awaitable[Any]], *args: Any) -> bool:
        def start() -> None:
            # The factory is invoked only on the running page loop, so a failed
            # cross-thread submission cannot leak an unawaited coroutine.
            task = self.page.loop.create_task(handler(*args))
            self._tasks.add(task)
            task.add_done_callback(self._task_done)
        return self.post(start)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error and not self._closed.is_set():
                logger.error('UI task failed: %s', type(error).__name__, exc_info=error)
