"""The DevOps watch (D1): the last report, refreshed on a cadence, posted daily.

`OpsWatch` keeps the latest `OpsReport` for the Ops card and `/api/devops`
(a page never waits for ssh or GitHub), refreshes it every
`interval_s` in the server's loop, and posts the daily report on the chat
once a day after `report_hour_utc` when a chat adapter is configured.
Everything here is read-only; a failing refresh keeps the previous report
and says why.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Awaitable, Callable

from theswarm.agents.devops import UNKNOWN, Finding, OpsReport, format_report

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 600
DEFAULT_REPORT_HOUR_UTC = 7
DEFAULT_REPORT_MINUTE = 30


def due_daily(now: datetime, last_posted: date | None, hour: int = DEFAULT_REPORT_HOUR_UTC,
              minute: int = DEFAULT_REPORT_MINUTE) -> bool:
    """Once a day, after the hour: not before it, never twice the same day."""
    now = now.astimezone(timezone.utc)
    if last_posted is not None and last_posted >= now.date():
        return False
    return (now.hour, now.minute) >= (hour, minute)


class OpsWatch:
    def __init__(self, gather: Callable[[], Awaitable[OpsReport]], *, interval_s: int = DEFAULT_INTERVAL_SECONDS,
                 report_hour_utc: int = DEFAULT_REPORT_HOUR_UTC, report_minute: int = DEFAULT_REPORT_MINUTE,
                 chat=None, channel: str = "", clock: Callable[[], datetime] | None = None) -> None:
        self._gather = gather
        self._interval = max(30, int(interval_s))
        self._hour = report_hour_utc
        self._minute = report_minute
        self._chat = chat
        self._channel = channel
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._last: OpsReport | None = None
        self._error: str = ""
        self.posted_on: date | None = None
        self.last_post: str = ""

    def configure_chat(self, chat, channel: str) -> None:
        """The daily report goes to this chat and channel (the server's, once connected)."""
        self._chat = chat
        self._channel = channel

    def last(self) -> OpsReport | None:
        return self._last

    @property
    def error(self) -> str:
        return self._error

    async def refresh(self) -> OpsReport:
        """Read everything again; a failure keeps the last report and is remembered."""
        async with self._lock:
            try:
                self._last = await self._gather()
                self._error = ""
            except Exception as exc:  # noqa: BLE001 — never a page's problem
                log.exception("DevOps: the refresh failed")
                self._error = str(exc)[:200] or exc.__class__.__name__
                if self._last is None:
                    self._last = OpsReport(
                        (Finding("devops", "DevOps", UNKNOWN, f"the readers failed: {self._error}"),),
                        read_at=self._clock(),
                    )
            return self._last

    async def latest(self) -> OpsReport:
        """The last report, read once when there is none yet."""
        return self._last if self._last is not None else await self.refresh()

    async def post_daily(self, now: datetime | None = None) -> bool:
        """Post the report on the chat when it is due; True when posted."""
        now = now or self._clock()
        if self._chat is None or not self._channel or not due_daily(now, self.posted_on, self._hour, self._minute):
            return False
        report = await self.latest()
        text = format_report(report)
        try:
            await self._chat.post_message(self._channel, text)
        except Exception:  # noqa: BLE001
            log.exception("DevOps: the daily report could not be posted")
            return False
        self.posted_on = now.astimezone(timezone.utc).date()
        self.last_post = now.isoformat()
        log.info("DevOps: daily report posted on %s (%s)", self._channel, report.status)
        return True

    async def run_loop(self) -> None:
        """Refresh on the cadence, post once a day; lives as long as the server."""
        while True:
            try:
                await self.refresh()
                await self.post_daily()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("DevOps: the watch loop failed a turn")
            await asyncio.sleep(self._interval)
