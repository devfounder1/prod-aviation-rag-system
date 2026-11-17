from __future__ import annotations

import asyncio
import gc
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
import warnings

from activity import ActivityEvent
from agent_files_ui import FileApproval
from jobs import JobController, RequestJob
from ui_dispatch import UiDispatcher


def test_closed_loop_never_constructs_coroutine_or_reports_ui_error() -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    page = SimpleNamespace(loop=loop, run_thread=MagicMock())
    closed = MagicMock()
    ui = UiDispatcher(page, closed)
    ran: list[str] = []
    async def handler() -> None:
        ran.append('unreachable')
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter('always')
        assert not ui.run_task(handler)
        assert not ui.run_thread(lambda: ran.append('thread'))
        gc.collect()
    assert not ran and not observed
    page.run_thread.assert_not_called()
    closed.assert_called_once()


def test_close_race_drops_factory_before_it_is_called(page_loop: asyncio.AbstractEventLoop) -> None:
    ui = UiDispatcher(SimpleNamespace(loop=page_loop))
    pending: list[Any] = []
    # Simulate successful enqueue followed by close before the page executes it.
    loop = SimpleNamespace(is_closed=lambda: False, is_running=lambda: True,
                           call_soon_threadsafe=lambda fn: pending.append(fn))
    ui.page = SimpleNamespace(loop=loop)
    handler = MagicMock()
    assert ui.run_task(handler)
    ui.close()
    for callback in pending:
        callback()
    handler.assert_not_called()


def test_waiting_approval_fails_closed_without_page_loop() -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    page = MagicMock(loop=loop)
    request = FileApproval(page, RequestJob('a'), lambda: True)
    assert not request.wait('Change original', timeout=0.1)
    page.open.assert_not_called()


def test_shutdown_cancels_job_and_voice_and_blocks_late_callbacks() -> None:
    from prilozhenie import AviationRAGApp
    loop = asyncio.new_event_loop()
    loop.close()
    app = AviationRAGApp.__new__(AviationRAGApp)
    app.page = MagicMock(loop=loop)
    app._jobs = JobController()
    job = app._jobs.start('a')
    app.chat_manager = SimpleNamespace(current_chat_id='a')
    app.wake_listener = MagicMock()
    app._voice_stop = MagicMock()
    app._queue_activity(job, ActivityEvent('thinking'))
    assert job.token['cancelled']
    assert app._jobs.current is None
    app.wake_listener.stop.assert_called_once()
    app._voice_stop.set.assert_called_once()
    app._queue_job_ui(job, MagicMock())
    app._process('old request', [], False, job, 'qwen2.5:14b', [])
    app.page.run_thread.assert_not_called()
    app._shutdown()
    app.wake_listener.stop.assert_called_once()


def test_close_during_model_callback_does_not_cascade_into_failure_ui() -> None:
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    loop_closed = [False]
    loop = SimpleNamespace(is_closed=lambda: loop_closed[0], is_running=lambda: not loop_closed[0],
                           call_soon_threadsafe=lambda fn: fn(), run_in_executor=lambda *args: MagicMock())
    app.page = MagicMock(loop=loop)
    app._jobs = JobController()
    job = app._jobs.start('a')
    app.chat_manager = SimpleNamespace(current_chat_id='a')
    app._chat_file_contexts = {}
    app.rag_system = MagicMock(model_name='qwen2.5:14b')
    app._fail_job = MagicMock()
    def query(*args: Any, **kwargs: Any) -> tuple[str, list[str]]:
        loop_closed[0] = True
        kwargs['on_activity'](ActivityEvent('thinking'))
        raise RuntimeError('Event loop is closed')
    app.rag_system.query_stream.side_effect = query
    app._process('request', [], False, job, 'qwen2.5:14b', [])
    assert job.token['cancelled']
    app._fail_job.assert_not_called()


def test_window_close_stops_workers_before_destroying_native_window() -> None:
    import flet as ft
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    app.page = MagicMock()
    app._shutdown = MagicMock()
    asyncio.run(app._on_window_event(SimpleNamespace(type=ft.WindowEventType.CLOSE)))
    app._shutdown.assert_called_once()
    app.page.window.destroy.assert_called_once()


def test_delete_dialog_does_not_cancel_until_confirmed() -> None:
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    app.page = MagicMock()
    app._jobs = JobController()
    job = app._jobs.start('a')
    app.chat_manager = MagicMock(current_chat_id='a', chats={'a': {'name': 'Test'}})
    app._cancel_active_job = MagicMock(side_effect=app._jobs.cancel)
    app._update_chat_list = MagicMock()
    app._load_current_chat = MagicMock()
    app._show_toast = MagicMock()
    app._delete_chat('a')
    dialog = app.page.open.call_args.args[0]
    assert not job.token['cancelled']
    dialog.actions[0].on_click(None)
    assert not job.token['cancelled']
    app._delete_chat('a')
    app.page.open.call_args.args[0].actions[1].on_click(None)
    assert job.token['cancelled']
    app.chat_manager.delete_chat.assert_called_once_with('a')


def test_executor_shutdown_race_is_not_an_unhandled_loop_callback() -> None:
    loop = MagicMock()
    loop.is_closed.return_value = False
    loop.is_running.return_value = True
    loop.call_soon_threadsafe.side_effect = lambda callback: callback()
    loop.run_in_executor.side_effect = RuntimeError('cannot schedule new futures after shutdown')
    on_close = MagicMock()
    ui = UiDispatcher(SimpleNamespace(loop=loop, executor=None), on_close)
    action = MagicMock()
    ui.run_thread(action)
    action.assert_not_called()
    on_close.assert_called_once()
    assert not ui.active
