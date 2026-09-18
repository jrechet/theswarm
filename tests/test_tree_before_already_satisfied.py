"""Work in the tree is committed before any ALREADY_SATISFIED is believed.

Cycle 5b1da00155c2, task #133: the Dev's first attempt edited the files in
place for 420s and timed out; the retry saw those edits in the working tree
and answered ALREADY_SATISFIED — a correct reading of the tree — and
implement_task closed the issue without committing: no commit, no PR, the
work reset at the next attempt, the issue closed for nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from theswarm.agents.dev import implement_task

TASK = {"number": 133, "title": "Persist the CLI timeout floor", "body": "Do it.\n\nParent: #79"}
SATISFIED = (
    "The store, migration, wiring and tests are already in the tree.\n"
    "ALREADY_SATISFIED: src/theswarm/infrastructure/persistence/cli_timeout_floor_store.py — already implemented"
)


def _github() -> AsyncMock:
    gh = AsyncMock()
    gh.add_comment = AsyncMock()
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    gh.close_issue = AsyncMock()
    gh.get_issues = AsyncMock(return_value=[])
    gh.get_open_prs = AsyncMock(return_value=[])
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.get_issue_comments = AsyncMock(return_value=[])
    return gh


def _claude(text: str) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=text, total_tokens=5, cost_usd=0.01))
    return claude


async def test_a_dirty_tree_is_committed_even_when_claude_says_already_satisfied(tmp_path):
    gh = _github()
    commit = AsyncMock(return_value=True)

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=commit), \
         patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="6 files changed")):
        result = await implement_task({
            "task": TASK, "claude": _claude(SATISFIED), "workspace": str(tmp_path), "github": gh,
        })

    commit.assert_awaited_once()
    gh.close_issue.assert_not_awaited()
    assert result["diff_stat"] == "6 files changed"
    assert not result.get("already_satisfied")


async def test_a_clean_tree_still_honours_already_satisfied(tmp_path):
    gh = _github()

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)):
        result = await implement_task({
            "task": TASK, "claude": _claude(SATISFIED), "workspace": str(tmp_path), "github": gh,
        })

    gh.close_issue.assert_awaited_once()
    assert result["already_satisfied"] is True


async def test_a_clean_tree_and_no_claim_is_still_no_changes(tmp_path):
    gh = _github()

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)):
        result = await implement_task({
            "task": TASK, "claude": _claude("Nothing to do here."), "workspace": str(tmp_path), "github": gh,
        })

    gh.close_issue.assert_not_awaited()
    assert result["result"] == "no changes produced"
