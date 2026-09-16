"""A failed attempt leaves a trace on the issue; the Dev is told about
its siblings' open PRs.

Both address the same week: every self-cycle re-tried #89 first because
nothing remembered it had failed the day before (#99), and four sub-tasks
of one story each re-implemented what the others had already put in a PR
(#104, #105, #108, #109 — one feature, four times).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.agents.dev import (
    ATTEMPT_MARKER,
    _note_failed_attempt,
    _prior_failures,
    _sibling_prs,
    implement_task,
)

TASK = {
    "number": 88, "title": "Close already-satisfied sub-tasks",
    "body": "Do it.\n\nParent: #85",
}


def _github() -> AsyncMock:
    gh = AsyncMock()
    gh.add_comment = AsyncMock()
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    gh.get_issues = AsyncMock(return_value=[])
    gh.get_open_prs = AsyncMock(return_value=[])
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.get_issue_comments = AsyncMock(return_value=[])
    return gh


def _claude(text: str = "Nothing to change here.") -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=text, total_tokens=5, cost_usd=0.01))
    return claude


class TestTheNote:
    async def test_it_carries_the_marker_and_the_reason(self):
        gh = _github()

        await _note_failed_attempt(gh, TASK, "CLI timed out after 546s")

        number, body = gh.add_comment.await_args.args
        assert number == 88
        assert body.startswith(ATTEMPT_MARKER)
        assert "CLI timed out after 546s" in body

    async def test_the_reason_is_bounded(self):
        gh = _github()

        await _note_failed_attempt(gh, TASK, "x" * 5000)

        assert len(gh.add_comment.await_args.args[1]) < 400

    async def test_no_github_no_note(self):
        await _note_failed_attempt(None, TASK, "whatever")  # does not raise

    async def test_a_failing_comment_call_is_swallowed(self):
        gh = _github()
        gh.add_comment = AsyncMock(side_effect=RuntimeError("503"))

        await _note_failed_attempt(gh, TASK, "reason")  # does not raise


class TestPriorFailures:
    async def test_counts_marked_comments_only(self):
        gh = _github()
        gh.get_issue_comments = AsyncMock(return_value=[
            {"body": f"{ATTEMPT_MARKER}\n⏱ Attempt failed — timeout"},
            {"body": "A human comment"},
            {"body": f"{ATTEMPT_MARKER}\n⏱ Attempt failed — no file changes"},
        ])

        assert await _prior_failures(gh, 89) == 2

    async def test_errors_count_as_zero(self):
        gh = _github()
        gh.get_issue_comments = AsyncMock(side_effect=RuntimeError("503"))

        assert await _prior_failures(gh, 89) == 0


class TestImplementTaskLeavesTheTrace:
    async def test_a_crash_before_the_call_is_noted(self, tmp_path):
        gh = _github()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock(side_effect=RuntimeError("git exploded"))):
            with pytest.raises(RuntimeError):
                await implement_task({
                    "task": TASK, "claude": _claude(), "workspace": str(tmp_path), "github": gh,
                })

        gh.add_labels.assert_awaited()  # requeued, as before
        body = gh.add_comment.await_args.args[1]
        assert body.startswith(ATTEMPT_MARKER)
        assert "git exploded" in body

    async def test_no_file_changes_is_noted(self, tmp_path):
        gh = _github()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)):
            result = await implement_task({
                "task": TASK, "claude": _claude(), "workspace": str(tmp_path), "github": gh,
            })

        assert result["result"] == "no changes produced"
        body = gh.add_comment.await_args.args[1]
        assert body.startswith(ATTEMPT_MARKER)
        assert "no file changes" in body

    async def test_a_committed_change_leaves_no_trace(self, tmp_path):
        gh = _github()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="1 file")):
            await implement_task({
                "task": TASK, "claude": _claude("--- FILE: x.py ---\n```python\nprint(1)\n```"),
                "workspace": str(tmp_path), "github": gh,
            })

        assert not any(
            call.args[1].startswith(ATTEMPT_MARKER) for call in gh.add_comment.await_args_list
        )


class TestSiblingPullRequests:
    def _github_with_siblings(self) -> AsyncMock:
        gh = _github()
        gh.get_issues = AsyncMock(return_value=[
            {"number": 89, "body": "e2e\n\nParent: #85"},
            {"number": 88, "body": "close\n\nParent: #85"},
            {"number": 87, "body": "report\n\nParent: #85"},
            {"number": 42, "body": "other\n\nParent: #12"},
        ])
        gh.get_open_prs = AsyncMock(return_value=[
            {"number": 104, "title": "[#89] Add end-to-end regression test"},
            {"number": 200, "title": "[#42] Unrelated story's task"},
            {"number": 201, "title": "chore: no task prefix"},
        ])
        gh.get_pr_files = AsyncMock(return_value=[
            {"filename": "src/theswarm/agents/dev.py"},
            {"filename": "tests/test_cycle_already_satisfied.py"},
        ])
        return gh

    async def test_lists_the_siblings_open_prs_with_their_files(self):
        section = await _sibling_prs(self._github_with_siblings(), TASK)

        assert "PR #104 [#89]" in section
        assert "src/theswarm/agents/dev.py" in section
        assert "ALREADY_SATISFIED" in section

    async def test_other_stories_and_unprefixed_prs_are_left_out(self):
        section = await _sibling_prs(self._github_with_siblings(), TASK)

        assert "#200" not in section
        assert "#201" not in section

    async def test_the_task_itself_is_not_its_own_sibling(self):
        gh = self._github_with_siblings()
        gh.get_open_prs = AsyncMock(return_value=[{"number": 105, "title": "[#88] Close already-satisfied"}])

        assert await _sibling_prs(gh, TASK) == ""

    async def test_no_parent_no_section(self):
        assert await _sibling_prs(self._github_with_siblings(), {"number": 1, "body": "loose task"}) == ""

    async def test_no_open_sibling_prs_no_section(self):
        gh = self._github_with_siblings()
        gh.get_open_prs = AsyncMock(return_value=[])

        assert await _sibling_prs(gh, TASK) == ""

    async def test_a_github_failure_yields_no_section_not_an_error(self):
        gh = self._github_with_siblings()
        gh.get_open_prs = AsyncMock(side_effect=RuntimeError("503"))

        assert await _sibling_prs(gh, TASK) == ""

    async def test_the_section_reaches_the_prompt(self, tmp_path):
        gh = self._github_with_siblings()
        claude = _claude()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)):
            await implement_task({
                "task": TASK, "claude": claude, "workspace": str(tmp_path), "github": gh,
            })

        prompt = claude.run.await_args.args[0]
        assert "Sibling pull requests already open" in prompt
        assert "PR #104" in prompt
        assert prompt.index("PR #104") < prompt.index("ALREADY_SATISFIED: path/to/file.py")
