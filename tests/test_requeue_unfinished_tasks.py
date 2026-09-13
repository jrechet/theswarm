"""A task claimed but not finished goes back to the queue.

Prod cycle 751202be0c3a was asked for an almost-sold-out warning. The
TechLead split it into four; the Dev delivered #216 and #219, and left #217
and #218 carrying status:in-progress — claimed, unfinished, and reported as
a completed cycle. That label reads as "someone is on it" when nobody is.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.cycle import _requeue_unfinished


def _issue(number, body="Parent: #215"):
    return {"number": number, "title": f"t{number}", "body": body}


def _config(target=215):
    return SimpleNamespace(target_issue=target, github_repo="jrechet/concert-tour-app")


def _github(children):
    gh = AsyncMock()
    gh.get_issues = AsyncMock(return_value=children)
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    return gh


# ── The production shape ───────────────────────────────────────────────


async def test_unfinished_children_are_handed_back():
    gh = _github([_issue(217), _issue(218)])
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        assert await _requeue_unfinished(_config()) == [217, 218]

    gh.add_labels.assert_any_await(217, ["status:ready"])
    gh.remove_label.assert_any_await(217, "status:in-progress")


async def test_another_features_work_is_never_touched():
    """An untargeted cycle has no claim over what others may be holding."""
    gh = _github([_issue(300, body="Parent: #299")])
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        assert await _requeue_unfinished(_config()) == []

    gh.add_labels.assert_not_awaited()


async def test_an_untargeted_cycle_hands_nothing_back():
    gh = _github([_issue(217)])
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        assert await _requeue_unfinished(_config(target=None)) == []

    gh.get_issues.assert_not_awaited()


async def test_nothing_in_progress_is_a_quiet_no_op():
    gh = _github([])
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        assert await _requeue_unfinished(_config()) == []


# ── Tidying must never take the cycle down with it ─────────────────────


async def test_a_github_failure_does_not_fail_the_cycle():
    gh = AsyncMock()
    gh.get_issues = AsyncMock(side_effect=RuntimeError("api.github.com is down"))
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        assert await _requeue_unfinished(_config()) == []


async def test_only_in_progress_work_is_requested():
    """Asking for everything would hand back tasks nobody ever claimed."""
    gh = _github([])
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        await _requeue_unfinished(_config())

    assert gh.get_issues.await_args.kwargs["labels"] == [
        "role:dev", "status:in-progress",
    ]
