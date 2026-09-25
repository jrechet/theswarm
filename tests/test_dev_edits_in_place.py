"""The Dev's working tree is the truth, not the last message.

Cycle 5f8f0f63f58c, iteration 2, task #114: Claude edited `routes/api.py`
in place (refused — print mode grants nothing), wrote the FILE blocks in
an intermediate message, and ended with a summary. `--output-format json`
carries only the final message, the extractor saw no block, and a five-
minute implementation became "no file changes produced" (#125).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.agents.dev import (
    ATTEMPT_MARKER,
    DEV_TASK_PROMPT,
    EDIT_PERMISSION_MODE,
    implement_task,
    retry_implement,
)
from theswarm.tools.claude import ClaudeCLI

TASK = {"number": 114, "title": "Add unified cycle JSON serializer", "body": "Do it.\n\nParent: #113"}

SUMMARY_ONLY = (
    "Good, cleaned up. The two files above — `routes/api.py` and "
    "`tests/presentation/test_web_app.py` — implement the shape requested."
)


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


def _claude(text: str = SUMMARY_ONLY) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=text, total_tokens=5, cost_usd=0.01))
    return claude


class TestTheImplementationCall:
    async def test_edits_inside_the_workspace_are_accepted(self, tmp_path):
        claude = _claude()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="1 file")):
            await implement_task({
                "task": TASK, "claude": claude, "workspace": str(tmp_path), "github": _github(),
            })

        assert claude.run.await_args.kwargs["permission_mode"] == EDIT_PERMISSION_MODE
        assert claude.run.await_args.kwargs["workdir"] == str(tmp_path)

    async def test_an_in_place_edit_needs_no_file_block(self, tmp_path):
        """No FILE block, but the tree changed: that is a delivery, not a failure."""
        gh = _github()

        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=True)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="2 files")):
            result = await implement_task({
                "task": TASK, "claude": _claude(SUMMARY_ONLY), "workspace": str(tmp_path), "github": gh,
            })

        assert result["diff_stat"] == "2 files"
        assert result["result"] != "no changes produced"
        assert not any(
            call.args[1].startswith(ATTEMPT_MARKER) for call in gh.add_comment.await_args_list
        )

    async def test_a_clean_tree_logs_how_the_answer_began(self, tmp_path, caplog):
        """The next reader should not need the transcript to see what Claude did instead."""
        with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
             patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
             caplog.at_level("WARNING", logger="theswarm.agents.dev"):
            result = await implement_task({
                "task": TASK, "claude": _claude(SUMMARY_ONLY), "workspace": str(tmp_path), "github": _github(),
            })

        assert result["result"] == "no changes produced"
        assert "Good, cleaned up." in caplog.text

    def test_the_prompt_prefers_in_place_edits_and_keeps_the_fallback(self):
        assert "Edit the files in place" in DEV_TASK_PROMPT
        assert "--- FILE: path/to/file.py ---" in DEV_TASK_PROMPT
        assert "final message" in DEV_TASK_PROMPT


class TestTheRetry:
    async def test_commits_what_the_tree_says_not_what_was_extracted(self, tmp_path):
        commit = AsyncMock(return_value=True)

        with patch("theswarm.tools.git.commit_all", new=commit), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="fixed 1 file")):
            result = await retry_implement({
                "retry_count": 0, "task": TASK, "claude": _claude(SUMMARY_ONLY),
                "workspace": str(tmp_path), "test_output": "FAILED x", "diff_stat": "old",
            })

        commit.assert_awaited_once()
        assert result["diff_stat"] == "fixed 1 file"
        assert result["retry_count"] == 1

    async def test_nothing_changed_keeps_the_previous_diff(self, tmp_path):
        with patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
             patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(side_effect=AssertionError("not asked"))):
            result = await retry_implement({
                "retry_count": 0, "task": TASK, "claude": _claude("I could not reproduce it."),
                "workspace": str(tmp_path), "test_output": "FAILED x", "diff_stat": "old",
            })

        assert result["diff_stat"] == "old"

    async def test_the_retry_call_accepts_edits_too(self, tmp_path):
        claude = _claude()

        with patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)):
            await retry_implement({
                "retry_count": 0, "task": TASK, "claude": claude,
                "workspace": str(tmp_path), "test_output": "FAILED x",
            })

        assert claude.run.await_args.kwargs["permission_mode"] == EDIT_PERMISSION_MODE
