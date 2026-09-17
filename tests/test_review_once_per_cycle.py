"""Each PR is reviewed once per cycle, unless its head moved.

Cycle 5f8f0f63f58c: the TechLead reviewed #124 in iteration 2 (approved,
held — this is SELF_REPO), reviewed it again in iteration 3 after #126,
and the 300s review phase timed out on the second pass; iteration 4 would
have reviewed all three again. Every pass cost ~$0.4 and 2–3 minutes per PR
for verdicts that could not change: nothing had been pushed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from theswarm.agents.techlead import _pr_key, poll_and_review_prs
from theswarm.config import AgentState

REVIEW = '{"decision": "APPROVE", "summary": "fine", "issues": []}'


def _github(prs: list[dict]) -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=prs)
    gh.get_pr_files = AsyncMock(return_value=[{"filename": "a.py", "patch": "+x", "additions": 1, "deletions": 0, "status": "modified"}])
    gh.submit_review = AsyncMock()
    gh.add_pr_comment = AsyncMock()
    return gh


def _claude() -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=REVIEW, total_tokens=10, cost_usd=0.4))
    return claude


def _pr(number: int, sha: str = "aaa") -> dict:
    return {"number": number, "title": f"[#{number}] t", "body": "", "head": f"feat/{number}", "head_sha": sha}


def test_the_key_is_number_and_head():
    assert _pr_key(_pr(124, "abc123")) == "124@abc123"
    assert _pr_key({"number": 124}) == "124"


async def test_a_pr_reviewed_earlier_this_cycle_is_skipped():
    gh = _github([_pr(124, "s1"), _pr(126, "s2")])
    claude = _claude()

    result = await poll_and_review_prs({"github": gh, "claude": claude, "reviewed_prs": ["124@s1"]})

    assert claude.run.await_count == 1
    assert [r["pr_number"] for r in result["reviews"]] == [126]
    assert sorted(result["reviewed_prs"]) == ["124@s1", "126@s2"]


async def test_a_pr_whose_head_moved_is_reviewed_again():
    gh = _github([_pr(124, "s9")])

    result = await poll_and_review_prs({"github": gh, "claude": _claude(), "reviewed_prs": ["124@s1"]})

    assert [r["pr_number"] for r in result["reviews"]] == [124]
    assert "124@s9" in result["reviewed_prs"]


async def test_the_list_is_extended_in_place_so_a_timeout_keeps_what_was_done():
    """The phase can be aborted between two reviews; the cycle holds the list."""
    seen: list[str] = []
    gh = _github([_pr(1, "a"), _pr(2, "b")])

    await poll_and_review_prs({"github": gh, "claude": _claude(), "reviewed_prs": seen})

    assert seen == ["1@a", "2@b"]


async def test_nothing_left_says_so_without_calling_claude():
    gh = _github([_pr(124, "s1")])
    claude = _claude()

    result = await poll_and_review_prs({"github": gh, "claude": claude, "reviewed_prs": ["124@s1"]})

    assert claude.run.await_count == 0
    assert result["reviews"] == []
    assert "already reviewed" in result["result"]


def test_the_state_key_is_declared():
    assert "reviewed_prs" in AgentState.__annotations__
