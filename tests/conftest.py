

import asyncio
import threading
from collections.abc import Iterator
import pytest


@pytest.fixture
def page_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """A real running page loop for cross-thread scheduling/close regression tests."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    loop.call_soon(ready.set)
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    assert ready.wait(3)
    try:
        yield loop
    finally:
        async def cancel_pending() -> None:
            current = asyncio.current_task()
            tasks = [task for task in asyncio.all_tasks() if task is not current]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run_coroutine_threadsafe(cancel_pending(), loop).result(timeout=3)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(3)
        loop.close()
