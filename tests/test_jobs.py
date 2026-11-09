import threading
from jobs import CancelToken, JobController, request_scope, track_response
from unittest.mock import MagicMock


def test_late_ui_callbacks_do_not_touch_new_job() -> None:
    jobs = JobController()
    old = jobs.start('a')
    newer = jobs.start('b')
    touched = []
    assert not jobs.apply(old, lambda: touched.append('old'))
    assert jobs.apply(newer, lambda: touched.append('new'))
    jobs.finish(old)
    assert jobs.current is newer
    jobs.finish(newer)
    assert not jobs.apply(newer, lambda: touched.append('late-token'))
    assert touched == ['new']


def test_cancel_closes_http_response() -> None:
    token = CancelToken()
    response = MagicMock()
    with request_scope(token) as active:
        assert active
        track_response(response)
        token['cancelled'] = True
        response.close.assert_called_once()
    late = MagicMock()
    token.on_cancel(late)
    late.assert_called_once()


def test_cancelled_waiter_never_enters_inference() -> None:
    token = CancelToken()
    entered = threading.Event()
    result = []
    def waiter() -> None:
        entered.set()
        with request_scope(token) as active:
            result.append(active)
    with request_scope(CancelToken()):
        thread = threading.Thread(target=waiter)
        thread.start()
        assert entered.wait(2)
        token['cancelled'] = True
        thread.join(2)
        assert not thread.is_alive()
    assert result == [False]


def test_gui_callback_checks_ownership_at_execution_time() -> None:
    from types import SimpleNamespace
    from prilozhenie import AviationRAGApp
    app = AviationRAGApp.__new__(AviationRAGApp)
    pending = []
    app.page = SimpleNamespace(run_thread=lambda fn, *args: pending.append((fn, args)))
    app.chat_manager = SimpleNamespace(current_chat_id='a')
    app._jobs = JobController()
    old = app._jobs.start('a')
    calls = []
    app._queue_job_ui(old, lambda: calls.append('stale'))
    app._jobs.start('b')
    app.chat_manager.current_chat_id = 'b'
    for fn, args in pending:
        fn(*args)
    assert calls == []
