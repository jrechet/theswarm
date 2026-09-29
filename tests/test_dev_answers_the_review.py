"""A review and the Dev's answer to it are a conversation, not a loop.

price-stats (cycle 79f45fdaadb9, 2026-09-29): PR #486 imported
`PriceStatsResponse` and `get_price_stats`, which its sibling #485 had
merged on main an iteration earlier. The reviewer saw only the diff and
asked for changes — "imported, never defined" — as CRITICAL. The Dev, on
the resumed branch, answered three iterations running "Everything is
already in place", committed nothing, and its answer went nowhere: the
head did not move, the TechLead had "nothing left to review", the task was
handed back unfinished and the feature — one route — scored a failure and
a regression.

Two fixes. The reviewer reads the repository (the clone, on main) when a
symbol the diff uses is not in it. And a Dev that changes nothing on a
sent-back branch answers the review: its answer goes on the PR, the head's
`theswarm/review` status goes back to pending, and the TechLead reviews
again with the answer in front of it — the cap still bounds the talk.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from theswarm.agents.dev import DEV_REPLY_MARKER, _should_run_gates, implement_task
from theswarm.agents.techlead import (
    CHANGES_MARKER,
    _review_single_pr,
    _verdict_of_status,
    poll_and_review_prs,
)

TASK = {"number": 483, "title": "Implement GET /api/v1/stats/prices endpoint",
        "body": "Do it.\n\nParent: #481"}
NOTE = [{"body": (
    f"{CHANGES_MARKER}\n**Changes requested** on PR #486 "
    "(branch `feat/issue-483-implement-get-api-v1-stats-prices-endpoi`)\n\n"
    "- CRITICAL src/routers/stats.py: PriceStatsResponse and get_price_stats are imported "
    "but never defined in this PR")}]
ANSWER = ("Everything is already in place: PriceStatsResponse is defined in "
          "src/schemas/stats.py and get_price_stats in src/services/stats_service.py, "
          "both merged on main with #485.")


def _github():
    gh = AsyncMock()
    gh.get_issue_comments = AsyncMock(return_value=NOTE)
    gh.get_open_prs = AsyncMock(return_value=[])
    return gh


def _claude_answering():
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        text="", structured={"status": "already_satisfied", "summary": ANSWER},
        total_tokens=30, cost_usd=0.2))
    return claude


async def _implement(tmp_path, *, committed=False, heads=("abc123", "abc123")):
    gh = _github()
    with patch("theswarm.tools.git.resume_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=committed)), \
         patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="2 files")), \
         patch("theswarm.tools.git.head_sha", new=AsyncMock(side_effect=list(heads))), \
         patch("theswarm.tools.git.remove_worktree", new=AsyncMock()):
        result = await implement_task({"task": TASK, "claude": _claude_answering(),
                                       "workspace": str(tmp_path), "github": gh})
    return result, gh


async def test_a_sent_back_task_that_changes_nothing_answers_the_review(tmp_path):
    result, gh = await _implement(tmp_path)

    assert result["answered_review"] == 486
    number, body = gh.add_comment.await_args.args
    assert number == 486 and body.startswith(DEV_REPLY_MARKER)
    assert "merged on main with #485" in body
    sha, state, description = gh.create_commit_status.await_args.args
    assert (sha, state) == ("abc123", "pending") and description.startswith("Dev answered")
    assert gh.create_commit_status.await_args.kwargs["context"] == "theswarm/review"
    gh.add_labels.assert_awaited_with(483, ["status:review"])
    gh.close_issue.assert_not_awaited()  # the PR is still the answer's subject
    assert _should_run_gates(result) == "end"


async def test_new_commits_are_not_an_answer(tmp_path):
    result, gh = await _implement(tmp_path, heads=("abc123", "def456"))

    assert "answered_review" not in result
    gh.create_commit_status.assert_not_awaited()


async def test_a_pending_answer_is_not_a_verdict():
    assert _verdict_of_status({"state": "pending",
                               "description": "Dev answered the review — to review again"}) is None


async def test_the_review_reads_the_answer_and_the_repository(tmp_path):
    gh = AsyncMock()
    gh.get_pr_files = AsyncMock(return_value=[
        {"filename": "src/routers/stats.py", "patch": "+from src.schemas import PriceStatsResponse",
         "additions": 1, "deletions": 0, "status": "modified"}])
    gh.get_issue_comments = AsyncMock(return_value=[{"body": f"{DEV_REPLY_MARKER}\n{ANSWER}"}])
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        text="", structured={"decision": "APPROVE", "summary": "the symbols are on main", "issues": []},
        total_tokens=20, cost_usd=0.05))
    pr = {"number": 486, "title": "[#483] Implement GET /api/v1/stats/prices endpoint", "body": "",
          "head": "feat/issue-483-x", "head_sha": "abc123"}

    review = await _review_single_pr(gh, claude, pr, "", workdir=str(tmp_path))

    assert review["decision"] == "APPROVE"
    prompt = claude.run.await_args.args[0]
    assert "The developer answered your last review" in prompt and "merged on main with #485" in prompt
    assert "may already exist on the base branch" in prompt
    assert claude.run.await_args.kwargs["workdir"] == str(tmp_path)


async def test_the_review_loop_passes_the_clone(tmp_path):
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=[{"number": 486, "title": "[#483] t", "body": "",
                                               "head": "feat/issue-483-x", "head_sha": "abc"}])
    gh.get_review_status = AsyncMock(return_value=None)
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.get_issue_comments = AsyncMock(return_value=[])
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        text="", structured={"decision": "APPROVE", "summary": "ok", "issues": []},
        total_tokens=1, cost_usd=0.0))

    await poll_and_review_prs({"github": gh, "claude": claude, "workspace": str(tmp_path),
                               "reviewed_prs": []})

    assert claude.run.await_args.kwargs["workdir"] == str(tmp_path)


async def test_the_cycle_sends_it_back_to_the_tech_lead(monkeypatch):
    from theswarm import cycle_graph

    async def run_phase(rt, key, role, coro):
        return {"task": TASK, "answered_review": 486, "tokens_used": 1, "cost_usd": 0.0}

    monkeypatch.setattr(cycle_graph, "_run_phase", run_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: None)
    monkeypatch.setattr(cycle_graph, "_accounted", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph, "_within_budget", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph._cycle(), "build_dev_graph", lambda: object())
    rt = SimpleNamespace(announce=AsyncMock(), progress=AsyncMock(), enter=AsyncMock(),
                         base_state={}, config=SimpleNamespace(github_repo="o/r"))

    out = await cycle_graph.dev_iter(
        {"iteration": 3, "reviewed_prs": ["486@abc123", "485@fff"], "claimed_tasks": []},
        SimpleNamespace(context=rt))

    assert out["reviewed_prs"] == ["485@fff"]
    assert out["dev_outcome"] == "review"
    said = [call.args[1] for call in rt.progress.await_args_list]
    assert any("answered the review on PR #486" in line for line in said)


def test_the_state_declares_it():
    from theswarm.config import AgentState

    assert "answered_review" in AgentState.__annotations__
