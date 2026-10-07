"""The theater's pinned issue is kept twenty seconds between polls (V3 M4).

Every render of the stage read the pinned issue again — every issue of the
repository, all states, page after page — and a page load took tens of
seconds on concert-tour-app, on the rate limit's account.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.application.services import pinned_issue as mod

REPO = "jrechet/concert-tour-app"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    mod.clear_cache()
    monkeypatch.setenv("SWARM_PINNED_CACHE_SECONDS", "20")
    yield
    mod.clear_cache()


def _github(children=2):
    ctx = patch("theswarm.tools.github.GitHubClient")
    klass = ctx.start()
    client = klass.return_value
    client.get_issue = AsyncMock(return_value={"number": 85, "title": "Harden input validation", "state": "open", "labels": []})
    client.get_issues = AsyncMock(return_value=[
        {"number": 86 + i, "title": f"piece {i}", "body": "Parent: #85", "state": "open", "labels": [{"name": "status:ready"}]}
        for i in range(children)
    ])
    return ctx, client


async def test_a_second_read_within_the_window_costs_nothing():
    ctx, client = _github()
    try:
        first = await mod.load_pinned_issue(REPO, 85, now=100.0)
        again = await mod.load_pinned_issue(REPO, 85, now=110.0)
    finally:
        ctx.stop()
    assert first.issue["number"] == 85 and len(first.children) == 2
    assert again is first
    assert client.get_issues.await_count == 1


async def test_after_the_window_the_issue_is_read_again():
    ctx, client = _github()
    try:
        await mod.load_pinned_issue(REPO, 85, now=100.0)
        await mod.load_pinned_issue(REPO, 85, now=121.0)
    finally:
        ctx.stop()
    assert client.get_issues.await_count == 2


async def test_another_issue_or_repository_is_its_own_entry():
    ctx, client = _github()
    try:
        await mod.load_pinned_issue(REPO, 85, now=100.0)
        await mod.load_pinned_issue(REPO, 86, now=100.0)
        await mod.load_pinned_issue("jrechet/yakoi", 85, now=100.0)
    finally:
        ctx.stop()
    assert client.get_issues.await_count == 3


async def test_a_failed_read_is_never_kept():
    ctx, client = _github()
    client.get_issues = AsyncMock(side_effect=RuntimeError("rate limited"))
    try:
        broken = await mod.load_pinned_issue(REPO, 85, now=100.0)
        assert broken.error.startswith("rate limited")
        client.get_issues = AsyncMock(return_value=[])
        healed = await mod.load_pinned_issue(REPO, 85, now=101.0)
    finally:
        ctx.stop()
    assert healed.error == "" and healed.issue["number"] == 85


async def test_the_suite_s_switch_turns_it_off(monkeypatch):
    monkeypatch.setenv("SWARM_PINNED_CACHE_SECONDS", "0")
    ctx, client = _github()
    try:
        await mod.load_pinned_issue(REPO, 85, now=100.0)
        await mod.load_pinned_issue(REPO, 85, now=100.5)
    finally:
        ctx.stop()
    assert client.get_issues.await_count == 2
