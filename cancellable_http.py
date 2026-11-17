"""Interrupt loopback HTTP reads even while Ollama has not sent response headers."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import socket
import ssl
from typing import Any

import httpcore
import httpx

from jobs import current_token


class RequestCancelled(RuntimeError):
    """The caller handles an interrupted local request as cancellation."""


class InterruptibleStream(httpcore.NetworkStream):
    def __init__(self, stream: httpcore.NetworkStream) -> None:
        self.stream = stream

    @contextmanager
    def _operation(self) -> Iterator[None]:
        token = current_token.get()
        if token is None:
            yield
            return
        if token.get('cancelled'):
            raise RequestCancelled('Request cancelled')
        sock = self.stream.get_extra_info('socket')

        def interrupt() -> None:
            if isinstance(sock, socket.socket):
                try:
                    # shutdown wakes a blocked recv; closing an httpx response here can wait on its reader.
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        remove = token.on_cancel(interrupt)
        try:
            if token.get('cancelled'):
                raise RequestCancelled('Request cancelled')
            yield
        finally:
            remove()  # An old request must never interrupt a subsequently reused connection.
            if token.get('cancelled'):
                raise RequestCancelled('Request cancelled')

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        with self._operation():
            return self.stream.read(max_bytes, timeout)

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        with self._operation():
            self.stream.write(buffer, timeout)

    def close(self) -> None:
        self.stream.close()

    def start_tls(self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
                  timeout: float | None = None) -> httpcore.NetworkStream:
        raise ValueError('Only local plain HTTP is supported')

    def get_extra_info(self, info: str) -> Any:
        return self.stream.get_extra_info(info)


class LoopbackBackend(httpcore.SyncBackend):
    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None,
                    socket_options: Any = None) -> httpcore.NetworkStream:
        if host != '127.0.0.1':
            raise ValueError('LLM transport only permits IPv4 loopback')
        token = current_token.get()
        if token is not None and token.get('cancelled'):
            raise RequestCancelled('Request cancelled')
        return InterruptibleStream(super().connect_tcp(
            host, port, min(timeout if timeout is not None else 2, 2), local_address, socket_options))


class CancellableHTTPTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__(trust_env=False)
        # httpx does not expose httpcore's network_backend argument. Keep this
        # adapter narrow and cover it with real loopback tests on locked versions.
        self._pool.close()
        self._pool = httpcore.ConnectionPool(network_backend=LoopbackBackend(), retries=0)
