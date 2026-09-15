"""On its own repository the swarm reviews, approves — and does not merge.

A merge to main redeploys this service, and the redeploy ends the cycle
that just merged: halfway through its review phase, before QA ever runs,
with the theater showing a cycle that simply vanished. Elsewhere the
TechLead keeps merging exactly as before.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.agents.techlead import merge_approved_prs
from theswarm.config import SELF_REPO

REVIEWS = [
    {"pr_number": 94, "decision": "APPROVE"},
    {"pr_number": 95, "decision": "REQUEST_CHANGES"},
    {"pr_number": 96, "decision": "APPROVE"},
]


def _github() -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=[
        {"number": 94, "head": "feat/close-issue"},
        {"number": 96, "head": "feat/report-why"},
    ])
    gh.merge_pr = AsyncMock()
    gh.delete_branch = AsyncMock()
    return gh


class TestOnItsOwnRepository:
    async def test_approved_prs_are_held_not_merged(self):
        gh = _github()

        out = await merge_approved_prs({
            "github": gh, "github_repo": SELF_REPO, "reviews": REVIEWS,
        })

        gh.merge_pr.assert_not_awaited()
        gh.delete_branch.assert_not_awaited()
        assert out["merged_prs"] == []
        assert out["held_prs"] == [94, 96]

    async def test_the_result_says_who_merges(self):
        out = await merge_approved_prs({
            "github": _github(), "github_repo": SELF_REPO, "reviews": REVIEWS,
        })

        assert "held for a human" in out["result"]
        assert "94" in out["result"] and "96" in out["result"]

    async def test_nothing_approved_means_nothing_held(self):
        out = await merge_approved_prs({
            "github": _github(), "github_repo": SELF_REPO,
            "reviews": [{"pr_number": 95, "decision": "REQUEST_CHANGES"}],
        })

        assert out["held_prs"] == []
        assert out["merged_prs"] == []


class TestEverywhereElse:
    async def test_approved_prs_are_still_merged(self):
        gh = _github()

        out = await merge_approved_prs({
            "github": gh, "github_repo": "jrechet/concert-tour-app", "reviews": REVIEWS,
        })

        assert gh.merge_pr.await_count == 2
        gh.merge_pr.assert_any_await(94, merge_method="squash")
        gh.merge_pr.assert_any_await(96, merge_method="squash")
        assert out["merged_prs"] == [94, 96]
        assert out["held_prs"] == []

    async def test_a_request_for_changes_is_still_not_merged(self):
        gh = _github()

        await merge_approved_prs({
            "github": gh, "github_repo": "jrechet/concert-tour-app", "reviews": REVIEWS,
        })

        merged = {call.args[0] for call in gh.merge_pr.await_args_list}
        assert 95 not in merged


class TestTheConstant:
    def test_self_repo_is_the_one_ci_deploys_from(self):
        """A typo here would silently turn the guard off."""
        assert SELF_REPO == "jrechet/theswarm"
