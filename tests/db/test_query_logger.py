"""query_logger: slow statements (>100ms) are logged, fast ones are not (#316)."""

from __future__ import annotations

import logging
import time

import aiosqlite
import pytest

from theswarm.infrastructure.persistence.query_logger import (
    SLOW_QUERY_THRESHOLD_MS,
    instrument_connection,
)

LOGGER_NAME = "theswarm.db.query_logger"


@pytest.fixture()
async def db():
    conn = await aiosqlite.connect(":memory:")
    instrument_connection(conn)
    try:
        yield conn
    finally:
        await conn.close()


async def test_query_under_threshold_not_logged(db, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)

    await db.execute("SELECT 1")

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert records == []


async def test_query_over_threshold_logged_with_duration(db, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    delay = (SLOW_QUERY_THRESHOLD_MS / 1000) + 0.05

    await db.create_function("slow_down", 1, lambda seconds: time.sleep(seconds) or 0)
    await db.execute("SELECT slow_down(?)", (delay,))

    records = [r for r in caplog.records if r.name == LOGGER_NAME]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].duration_ms > SLOW_QUERY_THRESHOLD_MS
    assert "slow_down" in records[0].sql
