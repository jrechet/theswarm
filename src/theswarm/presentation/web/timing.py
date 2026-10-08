"""Request timing — wall-clock duration for every response, so a slow page
is measured before it is guessed at (#316).

Pure-ASGI, matching ``shell.py``/``auth.py``: no buffering of streamed
responses (SSE).
"""

from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("theswarm.timing")

SLOW_REQUEST_THRESHOLD_MS = 500


class TimingMiddleware:
    """Stamps ``X-Response-Time-Ms`` and logs ``{method, path, status_code,
    duration_ms}`` — WARN past the slow threshold, INFO otherwise."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                headers = list(message.get("headers") or [])
                headers.append((b"x-response-time-ms", str(duration_ms).encode("latin-1")))
                message["headers"] = headers

                record = {
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status_code": message["status"],
                    "duration_ms": duration_ms,
                }
                level = logging.WARNING if duration_ms > SLOW_REQUEST_THRESHOLD_MS else logging.INFO
                log.log(level, json.dumps(record))

            await send(message)

        await self.app(scope, receive, send_wrapper)
