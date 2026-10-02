"""A PR is reviewed once per head, across cycles — not once per cycle.

concert-tour-app#307: its head (1289031) has not moved since 2026-09-24,
and every cycle since reviewed it again — twelve REQUEST_CHANGES reviews,
each with the same "zero test changes" finding, a `theswarm/review` status
and a "left for a person" comment on #306. #433, a PR the owner opened by
hand, was re-approved the same way on every cycle. A verdict cannot change
when the code did not: the swarm's own `theswarm/review` status on the head
(V2 M8) is the record, and a head that carries one is not reviewed again.
Its decision still counts — an approval from an earlier cycle whose CI was
still running then is merged now.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.agents.techlead import _verdict_of_status, poll_and_review_prs

REVIEW = '{"decision": "APPROVE", "summary": "fine", "issues": []}'
STALE = {"state": "failure",
         "description": "Changes requested: the diff contains zero test changes"}


def _pr(number: int, sha: str = "1289031") -> dict:
    return {"number": number, "title": f"[#{number - 1}] tests", "body": "",
            "head": f"feat/issue-{number - 1}-tests", "head_sha": sha}


def _github(prs: list[dict], status) -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=prs)
    gh.get_pr_files = AsyncMock(return_value=[
        {"filename": "a.py", "patch": "+x", "additions": 1, "deletions": 0, "status": "modified"}])
    gh.get_review_status = AsyncMock(return_value=status)
    return gh


def _claude() -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=REVIEW, total_tokens=10, cost_usd=0.03))
    return claude


@pytest.mark.parametrize("description,decision,summary", [
    ("Approved: fine", "APPROVE", "fine"),
    ("Changes requested: no tests: none at all", "REQUEST_CHANGES", "no tests: none at all"),
    ("Commented: a note", "COMMENT", "a note"),
    ("Commented:", "COMMENT", ""),
])
def test_the_status_says_what_was_decided(description, decision, summary):
    assert _verdict_of_status({"state": "success", "description": description}) == (decision, summary)


@pytest.mark.parametrize("status", [
    None, {}, {"state": "success", "description": ""},
    {"state": "success", "description": "APPROVE"},  # not the swarm's wording
    MagicMock(),  # an unconfigured mock client answers anything
])
def test_anything_else_is_no_verdict(status):
    assert _verdict_of_status(status) is None


async def test_a_head_the_swarm_already_judged_is_not_reviewed_again():
    github, claude = _github([_pr(307)], STALE), _claude()

    out = await poll_and_review_prs({"github": github, "claude": claude, "reviewed_prs": []})

    claude.run.assert_not_awaited()
    github.create_pr_review.assert_not_awaited()
    github.add_comment.assert_not_awaited()  # no fresh "left for a person" on #306
    github.create_commit_status.assert_not_awaited()
    (review,) = out["reviews"]
    assert review["decision"] == "REQUEST_CHANGES" and review["earlier"] is True
    assert review["summary"] == "the diff contains zero test changes"
    assert out["reviewed_prs"] == ["307@1289031"] and out["cost_usd"] == 0.0
    github.get_review_status.assert_awaited_once_with("1289031")


async def test_an_earlier_approval_still_reaches_the_merge_pass():
    github = _github([_pr(431, "abc")], {"state": "success", "description": "Approved: good"})

    out = await poll_and_review_prs({"github": github, "claude": _claude(), "reviewed_prs": []})

    assert [(r["pr_number"], r["decision"]) for r in out["reviews"]] == [(431, "APPROVE")]


async def test_a_new_head_is_reviewed():
    github, claude = _github([_pr(448, "fresh")], None), _claude()

    out = await poll_and_review_prs({"github": github, "claude": claude, "reviewed_prs": []})

    claude.run.assert_awaited_once()
    (review,) = out["reviews"]
    assert review["decision"] == "APPROVE" and not review.get("earlier")


async def test_a_status_that_cannot_be_read_means_a_review():
    github, claude = _github([_pr(448, "fresh")], None), _claude()
    github.get_review_status = AsyncMock(side_effect=RuntimeError("502"))

    await poll_and_review_prs({"github": github, "claude": claude, "reviewed_prs": []})

    claude.run.assert_awaited_once()


async def test_the_cycle_says_the_verdict_is_an_earlier_one(monkeypatch):
    from theswarm import cycle_graph

    async def run_phase(rt, key, role, coro):
        return {"reviews": [{"pr_number": 307, "decision": "REQUEST_CHANGES", "earlier": True},
                            {"pr_number": 448, "decision": "APPROVE"}],
                "reviewed_prs": []}

    monkeypatch.setattr(cycle_graph, "_run_phase", run_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: None)
    monkeypatch.setattr(cycle_graph, "_accounted", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph, "_within_budget", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph._cycle(), "build_techlead_graph", lambda: object())
    rt = SimpleNamespace(announce=AsyncMock(), progress=AsyncMock(), base_state={},
                         config=SimpleNamespace(github_repo="o/r"))

    await cycle_graph.techlead_review({"iteration": 1}, SimpleNamespace(context=rt))

    said = [call.args[1] for call in rt.progress.await_args_list]
    assert "PR #307: REQUEST_CHANGES — unchanged since it was reviewed" in said
    assert "PR #448: APPROVE" in said


# ── The client ─────────────────────────────────────────────────────────


def _client(statuses):
    from theswarm.infrastructure.resilience import CircuitBreaker
    from theswarm.tools.github import GitHubClient

    commit = MagicMock()
    commit.get_combined_status.return_value = SimpleNamespace(statuses=statuses)
    with patch.object(GitHubClient, "__post_init__"):
        client = GitHubClient.__new__(GitHubClient)
        client.repo_name = "owner/repo"
        client._repo = MagicMock()
        client._repo.get_commit.return_value = commit
        client._gh = MagicMock()
        client._breaker = CircuitBreaker(name="test", failure_threshold=999)
    return client


async def test_the_client_reads_the_swarm_s_status_on_a_head():
    client = _client([
        SimpleNamespace(context="ci/tests", state="success", description="12 passed"),
        SimpleNamespace(context="theswarm/review", state="failure", description="Changes requested: x"),
    ])

    assert await client.get_review_status("1289031") == {
        "state": "failure", "description": "Changes requested: x"}
    client._repo.get_commit.assert_called_once_with("1289031")


async def test_a_head_without_it_answers_none():
    client = _client([SimpleNamespace(context="ci/tests", state="success", description="ok")])

    assert await client.get_review_status("abc") is None
