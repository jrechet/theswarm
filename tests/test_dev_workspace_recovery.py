"""A dirty workspace must not poison every later iteration.

Prod cycle 6ecb297eae40: an implementation attempt left modified files in
the reused workspace; `git checkout main` then refused, and because the
workspace is never cleaned, all five Dev iterations failed the same way and
the cycle finished having opened no PR.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.git import create_branch


@pytest.fixture()
def git_calls():
    calls: list[tuple[str, ...]] = []

    async def record(*args, **kwargs):
        calls.append(args)
        return ""

    with patch("theswarm.tools.git._run_git", side_effect=record), \
         patch("theswarm.tools.git.github_app.ensure_github_token",
               new=AsyncMock(return_value="")):
        yield calls


def _verbs(calls):
    return [next((a for a in c if not a.startswith("-")), "") for c in calls]


async def test_workspace_is_cleared_before_switching_branches(git_calls):
    await create_branch("/w", "feat/issue-49")
    verbs = _verbs(git_calls)
    assert verbs.index("reset") < verbs.index("checkout")
    assert verbs.index("clean") < verbs.index("checkout")


async def test_tracked_changes_are_discarded_hard(git_calls):
    await create_branch("/w", "feat/issue-49")
    assert ("reset", "--hard") in git_calls


async def test_untracked_files_are_removed_but_ignored_ones_survive(git_calls):
    """`clean -fd` without -x: the venv and caches must not be wiped."""
    await create_branch("/w", "feat/issue-49")
    assert ("clean", "-fd") in git_calls
    assert not any("-x" in c for c in git_calls if c and c[0] == "clean")


async def test_cleanup_never_aborts_the_branch_creation():
    """A fresh clone has nothing to reset; that must not fail the phase."""
    seen: list[dict] = []

    async def record(*args, **kwargs):
        seen.append({"args": args, "check": kwargs.get("check", True)})
        return ""

    with patch("theswarm.tools.git._run_git", side_effect=record), \
         patch("theswarm.tools.git.github_app.ensure_github_token",
               new=AsyncMock(return_value="")):
        await create_branch("/w", "feat/issue-49")

    for call in seen:
        if call["args"][:1] in (("reset",), ("clean",)):
            assert call["check"] is False


async def test_the_branch_is_still_reset_onto_base(git_calls):
    """The cleanup must not change what create_branch is for."""
    await create_branch("/w", "feat/issue-49", base="main")
    assert ("checkout", "main") in git_calls
    assert ("checkout", "-B", "feat/issue-49") in git_calls
