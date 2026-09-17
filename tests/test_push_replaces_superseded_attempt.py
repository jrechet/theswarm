"""A retried task's push replaces its previous attempt's branch.

The branch name is derived from the task, so a retry pushes the same name
as the attempt before it — whose PR was closed, but closing a PR does not
delete its branch. The push came back non-fast-forward on both retried
tasks of cycle 5f8f0f63f58c, with the good work in a local commit nobody
could see (#123).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools import git as git_ops


@pytest.fixture()
def calls(monkeypatch):
    """Every git argv `_run_git` was asked to run, in order."""
    seen: list[list[str]] = []

    async def fake_run_git(*args, cwd=None, check=True, timeout=None):
        seen.append(list(args))
        return ""

    monkeypatch.setattr(git_ops, "_run_git", fake_run_git)
    monkeypatch.setattr(git_ops.github_app, "ensure_github_token", AsyncMock(return_value=""))
    return seen


def _without_auth(argv: list[str]) -> list[str]:
    """Drop the `-c http.…extraheader=…` pair `_auth_args()` may prepend —
    never assert git argv by position."""
    out = []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg == "-c" and i + 1 < len(argv) and argv[i + 1].startswith("http."):
            skip = True
            continue
        out.append(arg)
    return out


async def test_fetches_the_remote_branch_before_pushing(calls):
    await git_ops.push_branch("/ws", "feat/issue-114-x")

    plain = [_without_auth(c) for c in calls]
    assert plain[0] == ["fetch", "origin", "feat/issue-114-x"]
    assert plain[1][0] == "push"


async def test_pushes_with_a_lease_not_a_blind_force(calls):
    await git_ops.push_branch("/ws", "feat/issue-114-x")

    push = _without_auth(calls[-1])
    assert "--force-with-lease" in push
    assert "--force" not in push
    assert "-f" not in push
    assert push[-2:] == ["origin", "feat/issue-114-x"]
    assert "-u" in push


async def test_the_fetch_is_best_effort_and_the_push_is_not(monkeypatch):
    """No remote branch, nothing to lease against: the fetch must not raise
    (check=False) while the push keeps failing loudly (check=True)."""
    seen: list[tuple[list[str], bool]] = []

    async def fake_run_git(*args, cwd=None, check=True, timeout=None):
        seen.append((list(args), check))
        return ""

    monkeypatch.setattr(git_ops, "_run_git", fake_run_git)
    monkeypatch.setattr(git_ops.github_app, "ensure_github_token", AsyncMock(return_value=""))

    await git_ops.push_branch("/ws", "feat/new")

    checks = {argv[[i for i, a in enumerate(argv) if a in ("fetch", "push")][0]]: check
              for argv, check in seen if "fetch" in argv or "push" in argv}
    assert checks == {"fetch": False, "push": True}


async def test_credentials_still_ride_along(calls, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

    await git_ops.push_branch("/ws", "feat/x")

    for argv in calls:
        assert any(arg.startswith("http.https://github.com/.extraheader=") for arg in argv)
