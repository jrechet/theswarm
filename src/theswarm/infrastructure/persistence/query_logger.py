"""Slow-query logging (#316).

The project talks to SQLite through ``aiosqlite``, not an ORM, so there is
no ``before_cursor_execute``/``after_cursor_execute`` pair to hook. Wrapping
the connection's own ``execute``/``executemany`` is the equivalent here:
same before/after timing, just at the aiosqlite entry points instead of a
SQLAlchemy engine.
"""

from __future__ import annotations

import logging
import time

import aiosqlite

log = logging.getLogger("theswarm.db.query_logger")

SLOW_QUERY_THRESHOLD_MS = 100


def instrument_connection(db: aiosqlite.Connection) -> aiosqlite.Connection:
    """Times every statement run through ``db``; logs the ones over threshold."""
    original_execute = db.execute
    original_executemany = db.executemany

    async def timed_execute(sql, parameters=None):
        start = time.perf_counter()
        cursor = await (original_execute(sql) if parameters is None else original_execute(sql, parameters))
        _log_if_slow(sql, start)
        return cursor

    async def timed_executemany(sql, parameters):
        start = time.perf_counter()
        cursor = await original_executemany(sql, parameters)
        _log_if_slow(sql, start)
        return cursor

    db.execute = timed_execute
    db.executemany = timed_executemany
    return db


def _log_if_slow(sql: str, start: float) -> None:
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    if duration_ms > SLOW_QUERY_THRESHOLD_MS:
        # Parameters never reach this log — only the statement text, which
        # holds placeholders, not values.
        log.warning(
            "slow query (%.2fms): %s",
            duration_ms,
            sql.strip(),
            extra={"duration_ms": duration_ms, "sql": sql.strip()},
        )
