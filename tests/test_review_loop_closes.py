"""A REQUEST_CHANGES review sends the task back to the Dev (#121).

Cycle 995128bb0600: the TechLead reviewed #118 — tests for a shape no
serializer produced — and asked for changes with a precise, correct list.
Then nothing. The task sat in `status:review`, which the picker skips, the
PR stayed open with red CI, and the review was read by nobody.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.agents.dev import _changes_requested, implement_task
from theswarm.agents.techlead import (
    CHANGES_MARKER,
    CHANGES_REQUESTED_CAP,
    poll_and_review_prs,
)

CHANGES = (
    '{"decision": "REQUEST_CHANGES", "summary": "The handler was never updated.",'
    ' "issues": [{"severity": "critical", "file": "routes/api.py",'
    ' "description": "the tests cannot pass against the current code"}]}'
)
TASK = {"number": 114, "title": "Add the serializer", "body": "Do it.\n\nParent: #113"}


def _pr(number: int = 118, issue: int = 114) -> dict:
    return {
        "number": number, "title": f"[#{issue}] Add the serializer",
        "body": f"## Summary\n\nImplements #{issue}\n\nCloses #{issue}",
        "head": f"feat/issue-{issue}-add-the-serializer", "head_sha": "abc",
    }


def _github(comments: list[dict] | None = None) -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=[_pr()])
    gh.get_pr_files = AsyncMock(return_value=[
        {"filename": "a.py", "patch": "+x", "additions": 1, "deletions": 0, "status": "modified"},
    ])
    gh.create_pr_review = AsyncMock()
    gh.add_comment = AsyncMock()
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    gh.get_issue_comments = AsyncMock(return_value=comments or [])
    gh.get_issues = AsyncMock(return_value=[])
    return gh


def _claude(text: str = CHANGES) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=text, total_tokens=5, cost_usd=0.1))
    return claude


class TestTheHandBack:
    async def test_the_task_goes_back_to_ready_with_the_review_on_the_issue(self):
        gh = _github()

        result = await poll_and_review_prs({"github": gh, "claude": _claude()})

        assert result["reviews"][0]["decision"] == "REQUEST_CHANGES"
        gh.add_labels.assert_awaited_with(114, ["status:ready"])
        gh.remove_label.assert_awaited_with(114, "status:review")
        number, body = gh.add_comment.await_args.args
        assert number == 114
        assert body.startswith(CHANGES_MARKER)
        assert "The handler was never updated." in body
        assert "routes/api.py" in body
        assert "#118" in body and "feat/issue-114-add-the-serializer" in body

    async def test_an_approval_sends_nothing_back(self):
        gh = _github()

        await poll_and_review_prs({
            "github": gh, "claude": _claude('{"decision": "APPROVE", "summary": "fine", "issues": []}'),
        })

        gh.add_labels.assert_not_awaited()
        gh.add_comment.assert_not_awaited()

    async def test_a_task_sent_back_too_often_is_left_for_a_person(self):
        gh = _github(comments=[{"body": CHANGES_MARKER + " round 1"}] * CHANGES_REQUESTED_CAP)

        await poll_and_review_prs({"github": gh, "claude": _claude()})

        # Still in review: a person decides, the loop does not spin.
        gh.add_labels.assert_not_awaited()
        body = gh.add_comment.await_args.args[1]
        assert CHANGES_MARKER not in body
        assert "changes were requested" in body.lower()

    async def test_a_pr_without_a_task_number_is_only_reviewed(self):
        gh = _github()
        gh.get_open_prs = AsyncMock(return_value=[
            {"number": 200, "title": "chore: no task prefix", "body": "", "head": "chore/x", "head_sha": "d"},
        ])

        await poll_and_review_prs({"github": gh, "claude": _claude()})

        gh.add_labels.assert_not_awaited()
        gh.add_comment.assert_not_awaited()


class TestTheNextAttempt:
    def _note(self) -> list[dict]:
        return [{"body": (
            f"{CHANGES_MARKER}\n**Changes requested** on PR #118 "
            "(branch `feat/issue-114-add-the-serializer`)\n\n"
            "The handler was never updated.\n\n- CRITICAL routes/api.py: the tests cannot pass"
        )}]

    async def test_the_review_reaches_the_dev_prompt(self, tmp_path):
        gh = _github(comments=self._note())
        claude = _claude("done")

        with patch("theswarm.tools.git.resume_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="1 file")):
            await implement_task({
                "task": TASK, "claude": claude, "workspace": str(tmp_path), "github": gh,
            })

        prompt = claude.run.await_args.args[0]
        assert "## Changes requested on your previous attempt" in prompt
        assert "The handler was never updated." in prompt
        assert "PR #118" in prompt

    async def test_the_previous_branch_is_reused_not_rebuilt(self, tmp_path):
        """`create_branch` resets from main — it would throw away the commits
        the review is about."""
        gh = _github(comments=self._note())
        resume = AsyncMock()
        fresh = AsyncMock()

        with patch("theswarm.tools.git.resume_branch", new=resume), \
             patch("theswarm.tools.git.create_branch", new=fresh), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="1 file")):
            result = await implement_task({
                "task": TASK, "claude": _claude("done"), "workspace": str(tmp_path), "github": gh,
            })

        resume.assert_awaited_once_with(str(tmp_path), "feat/issue-114-add-the-serializer")
        fresh.assert_not_awaited()
        assert result["branch"] == "feat/issue-114-add-the-serializer"

    async def test_without_a_note_the_branch_is_built_fresh(self, tmp_path):
        gh = _github()
        fresh = AsyncMock()

        with patch("theswarm.tools.git.create_branch", new=fresh), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="1 file")):
            await implement_task({
                "task": TASK, "claude": _claude("done"), "workspace": str(tmp_path), "github": gh,
            })

        fresh.assert_awaited_once()

    async def test_the_note_is_read_from_the_last_one(self):
        gh = _github(comments=[
            {"body": f"{CHANGES_MARKER}\nold, on PR #100 (branch `feat/old`)\n\nfirst round"},
            {"body": "unrelated chatter"},
            {"body": f"{CHANGES_MARKER}\nnew, on PR #118 (branch `feat/new`)\n\nsecond round"},
        ])

        note = await _changes_requested(gh, 114)

        assert note["pr_number"] == 118
        assert note["branch"] == "feat/new"
        assert "second round" in note["text"]

    async def test_no_note_is_none(self):
        assert await _changes_requested(_github(), 114) is None
