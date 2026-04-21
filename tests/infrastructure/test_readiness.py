"""Sprint G4 — HTTP readiness watchdog tests."""

from __future__ import annotations

import asyncio
import socket

import pytest

from theswarm.infrastructure.resilience.readiness import (
    ReadinessTimeout,
    wait_for_http_ready,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_response(status_line: str, body: bytes = b"ok") -> bytes:
    return (
        f"HTTP/1.1 {status_line}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body


async def _serve_one_response(port: int, status_line: str) -> asyncio.AbstractServer:
    """Start an asyncio TCP server that returns the same HTTP response to every request."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Drain the request line + headers
        try:
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
        except Exception:
            pass
        try:
            writer.write(_http_response(status_line))
            await writer.drain()
        except Exception:
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    return await asyncio.start_server(handle, "127.0.0.1", port)


async def test_returns_quickly_when_server_already_up():
    port = _free_port()
    server = await _serve_one_response(port, "200 OK")
    try:
        elapsed = await wait_for_http_ready(
            f"http://127.0.0.1:{port}/",
            timeout=5.0,
            interval=0.1,
        )
        assert elapsed < 2.0
    finally:
        server.close()
        await server.wait_closed()


async def test_waits_until_server_starts():
    port = _free_port()

    async def deferred_start() -> asyncio.AbstractServer:
        await asyncio.sleep(0.4)
        return await _serve_one_response(port, "200 OK")

    start_task = asyncio.create_task(deferred_start())

    try:
        elapsed = await wait_for_http_ready(
            f"http://127.0.0.1:{port}/",
            timeout=5.0,
            interval=0.1,
        )
        assert elapsed >= 0.3
        assert elapsed < 5.0
    finally:
        server = await start_task
        server.close()
        await server.wait_closed()


async def test_raises_when_server_never_starts():
    port = _free_port()
    with pytest.raises(ReadinessTimeout):
        await wait_for_http_ready(
            f"http://127.0.0.1:{port}/",
            timeout=0.5,
            interval=0.1,
        )


async def test_accepts_404():
    port = _free_port()
    server = await _serve_one_response(port, "404 Not Found")
    try:
        elapsed = await wait_for_http_ready(
            f"http://127.0.0.1:{port}/",
            timeout=3.0,
            interval=0.1,
        )
        assert elapsed < 2.0
    finally:
        server.close()
        await server.wait_closed()


async def test_rejects_5xx_until_deadline():
    port = _free_port()
    server = await _serve_one_response(port, "500 Internal Server Error")
    try:
        with pytest.raises(ReadinessTimeout):
            await wait_for_http_ready(
                f"http://127.0.0.1:{port}/",
                timeout=0.5,
                interval=0.1,
            )
    finally:
        server.close()
        await server.wait_closed()
