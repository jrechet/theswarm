"""Stale-while-revalidate for the pages' GitHub reads (2026-10-11: "l'application
est globalement très lente" — espace-client's board 2.8 s, a theater 1.5 s,
every visit after twenty seconds)."""

from __future__ import annotations

import asyncio

import pytest

from theswarm.application.services.swr_cache import Swr


def _swr(fresh=20.0, keep=600.0, timeout=5.0):
    return Swr("test", fresh=lambda: fresh, keep=lambda: keep, timeout=lambda: timeout)


class _Reads:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.count = 0

    async def __call__(self):
        self.count += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


async def _settle(cache=None):
    """Every read in flight has landed (or failed)."""
    for _ in range(5):
        await asyncio.sleep(0)
    if cache is not None:
        await asyncio.gather(*cache._inflight.values(), return_exceptions=True)


async def test_fresh_costs_nothing():
    cache, reads = _swr(), _Reads("a")
    assert await cache.get("k", reads, now=0) == "a"
    assert await cache.get("k", reads, now=10) == "a"
    assert reads.count == 1


async def test_stale_is_served_at_once_and_read_again_behind():
    cache, reads = _swr(), _Reads("a", "b")
    await cache.get("k", reads, now=0)

    assert await cache.get("k", reads, now=30) == "a"  # nobody waits
    await _settle(cache)
    assert await cache.get("k", reads, now=31) == "b"
    assert reads.count == 2


async def test_one_read_behind_however_many_ask():
    cache, reads = _swr(), _Reads("a", "b", "c")
    await cache.get("k", reads, now=0)

    await asyncio.gather(*(cache.get("k", reads, now=30) for _ in range(5)))
    await _settle(cache)

    assert reads.count == 2


async def test_too_old_waits_for_a_fresh_read():
    cache, reads = _swr(keep=60), _Reads("a", "b")
    await cache.get("k", reads, now=0)
    assert await cache.get("k", reads, now=61) == "b"


async def test_a_failure_is_never_kept_and_reaches_the_caller():
    cache, reads = _swr(), _Reads(RuntimeError("502"), "a")
    with pytest.raises(RuntimeError):
        await cache.get("k", reads, now=0)
    assert await cache.get("k", reads, now=1) == "a"


async def test_a_failed_refresh_keeps_serving_the_last_answer():
    cache, reads = _swr(), _Reads("a", RuntimeError("502"), "c")
    await cache.get("k", reads, now=0)
    assert await cache.get("k", reads, now=30) == "a"
    await _settle(cache)
    assert await cache.get("k", reads, now=31) == "a"


async def test_a_hanging_read_is_bounded_and_lands_later():
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return "late"

    cache = _swr(timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await cache.get("k", slow, now=0)
    gate.set()
    await _settle(cache)
    assert await cache.get("k", slow, now=1) == "late"


async def test_off_means_every_read_goes_to_github():
    cache, reads = _swr(fresh=0), _Reads("a", "b")
    await cache.get("k", reads, now=0)
    assert await cache.get("k", reads, now=0) == "b"


async def test_forget_makes_the_next_page_wait_for_github():
    cache, reads = _swr(), _Reads("a", "b")
    await cache.get("k", reads, now=0)
    cache.forget("k")
    assert await cache.get("k", reads, now=1) == "b"


async def test_the_board_reads_issues_and_prs_side_by_side(monkeypatch):
    """Both GitHub reads of the board at once, kept per repository."""
    from unittest.mock import AsyncMock, patch

    from theswarm.presentation.web.routes import common

    monkeypatch.setenv("SWARM_BOARD_CACHE_SECONDS", "20")
    common._BOARD.clear()
    started: list[str] = []
    gate = asyncio.Event()

    async def issues():
        started.append("issues")
        await gate.wait()
        return [{"number": 1}]

    async def prs():
        started.append("prs")
        await gate.wait()
        return [{"number": 2, "title": "[#1] x", "body": ""}]

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(side_effect=issues)
        klass.return_value.get_open_pr_briefs = AsyncMock(side_effect=prs)
        reading = asyncio.ensure_future(common.board_reads("jrechet/espace-client"))
        await _settle()
        assert sorted(started) == ["issues", "prs"]  # neither waited for the other
        gate.set()
        board = await reading
        again = await common.board_reads("jrechet/espace-client")
    common._BOARD.clear()
    assert board == ([{"number": 1}], [{"number": 2, "title": "[#1] x", "body": ""}])
    assert again is board and klass.return_value.get_issues.await_count == 1
