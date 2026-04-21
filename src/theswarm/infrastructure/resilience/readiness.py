"""Sprint G4 — wait for an HTTP server to become ready before probing it.

The QA agent used to `await asyncio.sleep(3)` after starting uvicorn, which
left 10-30% of cycles racing the server and producing flaky connection errors.
`wait_for_http_ready` replaces that with a short-poll that returns early on
first 2xx/3xx/404 response and raises `ReadinessTimeout` if the deadline passes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

log = logging.getLogger(__name__)


class ReadinessTimeout(TimeoutError):
    """Raised when a server never returns a response within the timeout."""


async def wait_for_http_ready(
    url: str,
    *,
    timeout: float = 30.0,
    interval: float = 0.5,
    accept_statuses: tuple[int, ...] = (200, 204, 301, 302, 307, 308, 404),
    clock: Callable[[], float] = time.monotonic,
) -> float:
    """Poll `url` with short HTTP GETs until a response arrives.

    Returns the elapsed seconds on first acceptance.

    A 404 is accepted because the server may not expose a root route yet —
    what matters is that the socket is accepting connections and uvicorn is
    serving. A 5xx is rejected because the app has not finished booting.

    Raises `ReadinessTimeout` if `timeout` seconds pass with no successful
    probe. Import of `httpx` is deferred so that environments without it
    (e.g. test fixtures using ASGITransport) do not pay the import cost.
    """
    import httpx

    deadline = clock() + timeout
    attempts = 0
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=interval * 4) as client:
        while True:
            attempts += 1
            try:
                resp = await client.get(url)
                if resp.status_code in accept_statuses:
                    elapsed = clock() - (deadline - timeout)
                    log.info(
                        "readiness: %s ready after %.2fs (%d attempt%s, status=%d)",
                        url, elapsed, attempts, "s" if attempts != 1 else "",
                        resp.status_code,
                    )
                    return elapsed
                last_error = f"status={resp.status_code}"
            except (httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if clock() >= deadline:
                raise ReadinessTimeout(
                    f"server at {url} not ready after {timeout:.1f}s "
                    f"({attempts} attempts, last: {last_error})",
                )

            await asyncio.sleep(interval)
