"""On a target the swarm's approval is final; on its own repo it merges only its own.

2026-09-29: review all, merge only the swarm's own branches (`feat/issue-<n>-…`,
`feat/us-<n>-…`) — concert-tour-app#396, opened by hand, had been merged by a
demo cycle's TechLead where a person's review was the rule. 2026-10-06, the
owner: "I will never review concert-tour-app PRs; if the swarm says it's
good, then it's good. I only review DEMO." — Renovate's #507 and the owner's
own #433 had sat approved for a week, left for a person who never comes. On
a target every approved PR merges (green CI still required); "left for its
author" survives on SELF_REPO only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.agents.techlead import is_swarm_branch, merge_approved_prs
from theswarm.config import SELF_REPO


@pytest.mark.parametrize("branch,own", [
    ("feat/issue-306-write-backend-tests-for-city-filtering-o", True),
    ("feat/us-001-user-registration", True),
    ("feat/us001-login", True),
    ("chore/demo-fresh-db", False),
    ("feat/close-issue", False),
    ("fix/board-truth", False),
    ("", False),
    (None, False),
])
def test_the_swarm_s_own_branches(branch, own):
    assert is_swarm_branch(branch) is own


def _github(prs):
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=prs)
    gh.get_ci_checks = AsyncMock(return_value=[])
    gh.merge_pr = AsyncMock()
    gh.delete_branch = AsyncMock()
    gh.get_issue = AsyncMock(return_value=None)
    gh.get_issues = AsyncMock(return_value=[])
    return gh


PRS = [
    {"number": 425, "head": "chore/demo-fresh-db", "title": "chore(demo): a database of its own",
     "body": ""},
    {"number": 430, "head": "feat/issue-429-ical-feed", "title": "[#429] iCal feed",
     "body": "Closes #429"},
]
REVIEWS = [{"pr_number": 425, "decision": "APPROVE"}, {"pr_number": 430, "decision": "APPROVE"}]


async def test_on_a_target_an_approved_pr_the_swarm_did_not_open_merges_too():
    """The owner's rule of 2026-10-06: the swarm's approval is final."""
    github = _github(PRS)

    out = await merge_approved_prs({"github": github, "github_repo": "jrechet/concert-tour-app",
                                    "reviews": REVIEWS})

    merged = [call.args[0] for call in github.merge_pr.await_args_list]
    assert merged == [425, 430]
    assert out["merged_prs"] == [425, 430] and out["foreign_prs"] == []
    assert "left for its author" not in out["result"]


async def test_on_its_own_repo_only_its_own_are_held_for_the_end():
    github = _github(PRS)

    out = await merge_approved_prs({"github": github, "github_repo": SELF_REPO, "reviews": REVIEWS})

    assert out["held_prs"] == [430] and out["foreign_prs"] == [425]
    github.merge_pr.assert_not_awaited()


def test_the_graph_state_declares_the_foreign_prs():
    from theswarm.config import AgentState

    assert "foreign_prs" in AgentState.__annotations__


async def test_the_cycle_says_so(monkeypatch):
    from types import SimpleNamespace

    from theswarm import cycle_graph

    async def run_phase(rt, key, role, coro):
        return {"reviews": [], "reviewed_prs": [], "foreign_prs": [425]}

    monkeypatch.setattr(cycle_graph, "_run_phase", run_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: None)
    monkeypatch.setattr(cycle_graph, "_accounted", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph, "_within_budget", lambda *a, **k: {})
    monkeypatch.setattr(cycle_graph._cycle(), "build_techlead_graph", lambda: object())
    rt = SimpleNamespace(announce=AsyncMock(), progress=AsyncMock(), base_state={},
                         config=SimpleNamespace(github_repo="o/r"))

    await cycle_graph.techlead_review({"iteration": 1}, SimpleNamespace(context=rt))

    said = [call.args[1] for call in rt.progress.await_args_list]
    assert any("PR #425" in line and "left for its author" in line for line in said)
