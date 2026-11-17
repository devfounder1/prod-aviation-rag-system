from __future__ import annotations

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import Any

import httpx
import pytest

from cancellable_http import CancellableHTTPTransport, RequestCancelled
from jobs import CancelToken, request_scope


@pytest.fixture
def slow_server() -> Iterator[tuple[str, threading.Event, threading.Event]]:
    reached = threading.Event()
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_GET(self) -> None:
            if self.path == '/headers':
                reached.set()
                release.wait(5)
            try:
                self.send_response(200)
                self.send_header('Content-Length', '100' if self.path == '/stream' else '2')
                self.end_headers()
                if self.path == '/stream':
                    self.wfile.write(b'first')
                    self.wfile.flush()
                    # A long declared body creates a blocked read after the first bytes.
                else:
                    self.wfile.write(b'ok')
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args: Any) -> None:
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', reached, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize('path', ['/headers', '/stream'])
def test_stop_interrupts_headers_and_stream_and_next_request_works(
    slow_server: tuple[str, threading.Event, threading.Event], path: str,
) -> None:
    url, reached, release = slow_server
    token = CancelToken()
    received = threading.Event()
    failures: list[BaseException] = []
    with httpx.Client(transport=CancellableHTTPTransport(), trust_env=False, timeout=30) as client:
        def worker() -> None:
            try:
                with request_scope(token):
                    with client.stream('GET', url + path) as response:
                        for _ in response.iter_bytes():
                            received.set()
            except BaseException as exc:
                failures.append(exc)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert (reached if path == '/headers' else received).wait(3)
        started = time.monotonic()
        token['cancelled'] = True
        thread.join(2)
        assert not thread.is_alive()
        assert time.monotonic() - started < 2
        assert failures and isinstance(failures[0], RequestCancelled)
        release.set()
        with request_scope(CancelToken()):
            assert client.get(url + '/ok').text == 'ok'
        assert not token._closers
