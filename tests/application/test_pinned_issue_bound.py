"""A read that hangs must not hang the page (2026-10-09: a GitHub ReadTimeout,
retried by PyGithub, held a theater's first render for 35 minutes).

`load_pinned_issue` waits `SWARM_PINNED_TIMEOUT_SECONDS`, then answers with
the panel's error and lets the page draw; the read goes on, every page that
asks meanwhile waits on that same read, and its answer is kept once it lands.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.application.services import pinned_issue as pi


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setenv("SWARM_PINNED_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setenv("SWARM_PINNED_CACHE_SECONDS", "20")
    pi.clear_cache()
    yield
    pi.clear_cache()


async def test_a_hanging_read_is_bounded_shared_and_kept_once_it_lands():
    released = asyncio.Event()

    async def slow_issue(n):
        await released.wait()
        return {"number": n, "title": "Occupancy", "state": "open"}

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(side_effect=slow_issue)
        klass.return_value.get_issues = AsyncMock(return_value=[])
        first = await pi.load_pinned_issue("o/r", 42)
        assert first.issue is None and first.error.startswith("GitHub did not answer")
        second = await pi.load_pinned_issue("o/r", 42)
        assert second.error.startswith("GitHub did not answer") and klass.call_count == 1  # the same read, not a new one
        released.set()
        await asyncio.sleep(0.05)
        landed = await pi.load_pinned_issue("o/r", 42)
        assert landed.issue["title"] == "Occupancy" and klass.call_count == 1  # kept: no new read


async def test_a_quick_read_is_unchanged_and_a_failure_is_not_kept():
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(side_effect=RuntimeError("401"))
        failed = await pi.load_pinned_issue("o/r", 7)
        assert failed.error == "401" and failed.issue is None
        klass.return_value.get_issue = AsyncMock(return_value={"number": 7, "title": "Seven", "state": "open"})
        klass.return_value.get_issues = AsyncMock(return_value=[{"number": 8, "title": "child", "body": "Parent: #7", "state": "open", "labels": []}])
        ok = await pi.load_pinned_issue("o/r", 7)
        assert ok.issue["title"] == "Seven" and [c["number"] for c in ok.children] == [8]
    assert (await pi.load_pinned_issue("o/r", None)).issue is None
