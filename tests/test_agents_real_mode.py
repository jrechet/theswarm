"""Tests for agent real-mode code paths (github and claude are not None).

These complement the existing stub-mode tests by exercising the branches where
the mock GitHub and Claude clients are actually used.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build mock clients
# ---------------------------------------------------------------------------

def _mock_claude_result(text: str = "{}", tokens: int = 100, cost: float = 0.01):
    """Return a MagicMock that looks like a ClaudeCLI.run() result."""
    r = MagicMock()
    r.text = text
    r.total_tokens = tokens
    r.cost_usd = cost
    return r


def _make_claude(**overrides) -> MagicMock:
    mock = MagicMock()
    mock.run = AsyncMock(return_value=_mock_claude_result())
    mock.run_tests = AsyncMock(return_value={
        "passed": True, "output": "1 passed in 0.5s", "exit_code": 0,
    })
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


def _make_github(**overrides) -> AsyncMock:
    mock = AsyncMock()
    mock.get_issues = AsyncMock(return_value=[])
    mock.add_labels = AsyncMock()
    mock.remove_label = AsyncMock()
    mock.create_issue = AsyncMock(return_value={"number": 99, "title": "Task"})
    mock.get_open_prs = AsyncMock(return_value=[])
    mock.get_pr_files = AsyncMock(return_value=[])
    mock.create_pr = AsyncMock(return_value={"number": 10, "url": "https://github.com/o/r/pull/10"})
    mock.create_pr_review = AsyncMock()
    mock.merge_pr = AsyncMock()
    mock.delete_branch = AsyncMock()
    mock.get_file_content = AsyncMock(return_value="file content")
    mock.update_file = AsyncMock()
    mock.add_comment = AsyncMock()
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


def _base_state(*, github=None, claude=None, **extra) -> dict:
    return {
        "github": github,
        "claude": claude,
        "phase": "morning",
        "context": "test project context",
        **extra,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PO Agent
# ═══════════════════════════════════════════════════════════════════════════

class TestPOSelectDailyIssues:
    """Tests for po.select_daily_issues in real mode."""

    @pytest.fixture
    def backlog_issues(self):
        return [
            {"number": 1, "title": "US-001: Add login", "body": "Login feature",
             "labels": [{"name": "status:backlog"}], "state": "open",
             "assignees": [], "url": "https://github.com/o/r/issues/1"},
            {"number": 2, "title": "US-002: Add logout", "body": "Logout feature",
             "labels": [{"name": "status:backlog"}], "state": "open",
             "assignees": [], "url": "https://github.com/o/r/issues/2"},
        ]

    async def test_select_daily_issues_real_mode(self, backlog_issues):
        from theswarm.agents.po import select_daily_issues

        selected_json = json.dumps({
            "selected": [
                {"number": 1, "title": "US-001: Add login", "reason": "High priority"},
            ],
            "daily_plan": "Today we focus on login.",
        })
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(selected_json)))
        github = _make_github(get_issues=AsyncMock(return_value=backlog_issues))

        result = await select_daily_issues(_base_state(github=github, claude=claude))

        assert result["daily_plan"] == "Today we focus on login."
        assert result["tokens_used"] == 100
        # Labels should have been updated for issue #1
        github.remove_label.assert_awaited_once_with(1, "status:backlog")
        github.add_labels.assert_awaited_once_with(1, ["status:ready"])

    async def test_select_daily_issues_no_backlog(self):
        from theswarm.agents.po import select_daily_issues

        github = _make_github(get_issues=AsyncMock(return_value=[]))
        claude = _make_claude()

        result = await select_daily_issues(_base_state(github=github, claude=claude))

        assert "No backlog issues" in result.get("daily_plan", "") or "No backlog" in result.get("result", "")
        claude.run.assert_not_awaited()

    async def test_select_daily_issues_claude_invalid_json(self, backlog_issues):
        from theswarm.agents.po import select_daily_issues

        raw_text = "I could not produce JSON but here is a plan for today."
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(raw_text)))
        github = _make_github(get_issues=AsyncMock(return_value=backlog_issues))

        result = await select_daily_issues(_base_state(github=github, claude=claude))

        # When JSON parsing fails, daily_plan should fall back to the raw text
        assert result["daily_plan"] == raw_text
        # No labels should be updated because selected list is empty
        github.add_labels.assert_not_awaited()


class TestPOWriteDailyPlan:

    async def test_write_daily_plan_real_mode(self):
        from theswarm.agents.po import write_daily_plan

        github = _make_github()
        state = _base_state(github=github, daily_plan="Today we build login.")

        result = await write_daily_plan(state)

        assert "Daily plan written" in result["result"]
        github.update_file.assert_awaited_once()
        call_kwargs = github.update_file.call_args.kwargs
        assert call_kwargs["branch"] == "main"
        assert "Today we build login." in call_kwargs["content"]


class TestPOValidateDemo:

    async def test_validate_demo_real_mode(self):
        from theswarm.agents.po import validate_demo

        report_text = "# Validation\nAll tests pass."
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(report_text)))
        demo = {"date": "2025-01-01", "overall_status": "green"}

        state = _base_state(claude=claude, demo_report=demo)
        result = await validate_demo(state)

        assert result["daily_report"] == report_text
        assert result["tokens_used"] == 100
        claude.run.assert_awaited_once()


class TestPOWriteDailyReport:

    async def test_write_daily_report_real_mode(self):
        from theswarm.agents.po import write_daily_report

        github = _make_github()
        state = _base_state(github=github, daily_report="Everything shipped.")

        result = await write_daily_report(state)

        assert "Daily report written" in result["result"]
        github.update_file.assert_awaited_once()
        call_kwargs = github.update_file.call_args.kwargs
        assert "Everything shipped." in call_kwargs["content"]


# ═══════════════════════════════════════════════════════════════════════════
# Dev Agent
# ═══════════════════════════════════════════════════════════════════════════

_DEV_TASK = {
    "number": 5,
    "title": "US-001: Implement login endpoint",
    "body": "Create POST /login",
    "labels": [{"name": "role:dev"}, {"name": "status:ready"}],
    "state": "open",
    "assignees": [],
    "url": "https://github.com/o/r/issues/5",
}


class TestDevPickTask:

    async def test_pick_task_real_mode(self):
        from theswarm.agents.dev import pick_task

        github = _make_github(
            get_issues=AsyncMock(return_value=[_DEV_TASK]),
        )
        state = _base_state(github=github)
        result = await pick_task(state)

        assert result["task"] is not None
        assert result["task"]["number"] == 5
        github.add_labels.assert_awaited_once_with(5, ["status:in-progress"])
        github.remove_label.assert_awaited_once_with(5, "status:ready")

    async def test_pick_task_no_ready_tasks(self):
        from theswarm.agents.dev import pick_task

        github = _make_github(get_issues=AsyncMock(return_value=[]))
        state = _base_state(github=github)
        result = await pick_task(state)

        assert result["task"] is None


class TestDevImplementTask:

    async def test_implement_task_no_task(self):
        from theswarm.agents.dev import implement_task

        state = _base_state(task=None)
        result = await implement_task(state)

        assert result["result"] == "no task"

    @patch("theswarm.tools.git.get_diff_stat", new_callable=AsyncMock, return_value="1 file changed, 10 insertions(+)")
    @patch("theswarm.tools.git.commit_all", new_callable=AsyncMock, return_value=True)
    @patch("theswarm.tools.git.create_branch", new_callable=AsyncMock)
    async def test_implement_task_real_mode(self, mock_create_branch, mock_commit, mock_diff):
        from theswarm.agents.dev import implement_task

        impl_text = "Implemented the login endpoint with JWT tokens."
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(impl_text)))
        state = _base_state(
            claude=claude,
            task=_DEV_TASK,
            workspace="/tmp/test-workspace",
        )

        result = await implement_task(state)

        mock_create_branch.assert_awaited_once()
        branch_arg = mock_create_branch.call_args[0][1]
        assert branch_arg.startswith("feat/")
        claude.run.assert_awaited_once()
        mock_commit.assert_awaited_once()
        assert result["branch"] == branch_arg
        assert result["diff_stat"] == "1 file changed, 10 insertions(+)"


# ═══════════════════════════════════════════════════════════════════════════
# TechLead Agent
# ═══════════════════════════════════════════════════════════════════════════

class TestTechLeadBreakdownStories:

    async def test_breakdown_stories_real_mode(self):
        from theswarm.agents.techlead import breakdown_stories

        ready_issue = {
            "number": 3, "title": "US-003: Add search", "body": "Full-text search",
            "labels": [{"name": "status:ready"}], "state": "open",
        }
        tasks_json = json.dumps([
            {"title": "Add search index", "body": "Create Elasticsearch index", "labels": ["role:dev", "status:ready"]},
            {"title": "Add search endpoint", "body": "GET /search", "labels": ["role:dev", "status:ready"]},
        ])
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(tasks_json)))
        github = _make_github(get_issues=AsyncMock(return_value=[ready_issue]))

        result = await breakdown_stories(_base_state(github=github, claude=claude))

        assert "2 tasks" in result["result"]
        assert github.create_issue.await_count == 2
        # Parent issue should be updated
        github.remove_label.assert_awaited_with(3, "status:ready")
        github.add_labels.assert_awaited_with(3, ["status:in-progress"])

    async def test_breakdown_stories_no_ready(self):
        from theswarm.agents.techlead import breakdown_stories

        github = _make_github(get_issues=AsyncMock(return_value=[]))
        claude = _make_claude()

        result = await breakdown_stories(_base_state(github=github, claude=claude))

        assert "No issues to break down" in result["result"]
        claude.run.assert_not_awaited()


class TestTechLeadPollAndReviewPRs:

    @pytest.fixture
    def sample_pr(self):
        return {
            "number": 10,
            "title": "[US-001] Implement login",
            "body": "Implements #5",
            "head": "feat/us-001-login",
        }

    @pytest.fixture
    def sample_files(self):
        return [
            {
                "filename": "src/auth.py",
                "status": "added",
                "additions": 30,
                "deletions": 0,
                "patch": "+def login():\n+    pass",
            }
        ]

    async def test_poll_and_review_prs_no_prs(self):
        from theswarm.agents.techlead import poll_and_review_prs

        github = _make_github(get_open_prs=AsyncMock(return_value=[]))
        claude = _make_claude()

        result = await poll_and_review_prs(_base_state(github=github, claude=claude))

        assert result["reviews"] == []
        assert "no open PRs" in result["result"]

    async def test_poll_and_review_prs_with_pr(self, sample_pr, sample_files):
        from theswarm.agents.techlead import poll_and_review_prs

        review_json = json.dumps({
            "decision": "APPROVE",
            "summary": "Looks good.",
            "issues": [],
        })
        claude = _make_claude(run=AsyncMock(return_value=_mock_claude_result(review_json)))
        github = _make_github(
            get_open_prs=AsyncMock(return_value=[sample_pr]),
            get_pr_files=AsyncMock(return_value=sample_files),
        )

        result = await poll_and_review_prs(_base_state(github=github, claude=claude))

        assert len(result["reviews"]) == 1
        assert result["reviews"][0]["decision"] == "APPROVE"
        github.create_pr_review.assert_awaited_once()
        review_call = github.create_pr_review.call_args
        assert review_call.kwargs["event"] == "APPROVE"


class TestTechLeadMergeApprovedPRs:

    async def test_merge_approved_prs_approved(self):
        from theswarm.agents.techlead import merge_approved_prs

        reviews = [{"pr_number": 10, "decision": "APPROVE", "summary": "Good"}]
        pr_data = {"number": 10, "title": "PR", "head": "feat/us-001-login"}
        github = _make_github(get_open_prs=AsyncMock(return_value=[pr_data]))

        state = _base_state(github=github, reviews=reviews)
        result = await merge_approved_prs(state)

        github.merge_pr.assert_awaited_once_with(10, merge_method="squash")
        github.delete_branch.assert_awaited_once_with("feat/us-001-login")
        assert 10 in result["merged_prs"]

    async def test_merge_approved_prs_rejected(self):
        from theswarm.agents.techlead import merge_approved_prs

        reviews = [{"pr_number": 10, "decision": "REQUEST_CHANGES", "summary": "Needs work"}]
        github = _make_github()

        state = _base_state(github=github, reviews=reviews)
        result = await merge_approved_prs(state)

        github.merge_pr.assert_not_awaited()
        assert result.get("merged_prs") == []


# ═══════════════════════════════════════════════════════════════════════════
# QA Agent
# ═══════════════════════════════════════════════════════════════════════════

class TestQACollectIssueStatus:

    async def test_collect_issue_status_real_mode(self):
        from theswarm.agents.qa import collect_issue_status

        open_issues = [{"number": 1}, {"number": 2}, {"number": 3}]
        closed_issues = [{"number": 4}, {"number": 5}]

        async def fake_get_issues(*, state=None, labels=None, **kw):
            if state == "open":
                return open_issues
            if state == "closed":
                return closed_issues
            return []

        github = _make_github(get_issues=AsyncMock(side_effect=fake_get_issues))

        result = await collect_issue_status(_base_state(github=github))

        assert result["issue_stats"]["open"] == 3
        assert result["issue_stats"]["closed_today"] == 2


class TestQARunUnitTests:

    async def test_run_unit_tests_real_mode(self):
        from theswarm.agents.qa import run_unit_tests

        claude = _make_claude(
            run_tests=AsyncMock(return_value={
                "passed": True,
                "output": "===== 10 passed in 2.5s =====",
                "exit_code": 0,
            }),
        )
        state = _base_state(claude=claude, workspace="/tmp/ws")

        result = await run_unit_tests(state)

        assert result["tests_passed"] is True
        assert result["test_counts"]["passed"] == 10
        assert result["test_counts"]["failed"] == 0
        assert result["test_counts"]["total"] == 10

    async def test_run_unit_tests_failed(self):
        from theswarm.agents.qa import run_unit_tests

        claude = _make_claude(
            run_tests=AsyncMock(return_value={
                "passed": False,
                "output": "===== 3 passed, 2 failed in 4.1s =====",
                "exit_code": 1,
            }),
        )
        state = _base_state(claude=claude, workspace="/tmp/ws")

        result = await run_unit_tests(state)

        assert result["tests_passed"] is False
        assert result["test_counts"]["passed"] == 3
        assert result["test_counts"]["failed"] == 2
        assert result["test_counts"]["total"] == 5
