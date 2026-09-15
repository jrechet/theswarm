"""Breaking down the same issue twice must not duplicate its sub-tasks.

The guard asked whether the *parent* carried `role:dev`. Only sub-tasks ever
get that label, so the test matched nothing and every re-run of a cycle on
the same issue — a retry, a resume after a deploy, a second ▶ Play — created
a fresh copy of the whole breakdown. Found while re-running theswarm#85
after cancelling its first cycle: four sub-tasks were about to become eight.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.agents.techlead import _already_broken_down, breakdown_stories


def _issue(number: int, *, body: str = "", labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "body": body,
        "state": "open",
        "labels": labels or [],
    }


def _github(children: list[dict], *, target: dict | None = None) -> AsyncMock:
    gh = AsyncMock()
    gh.get_issues = AsyncMock(return_value=children)
    gh.get_issue = AsyncMock(return_value=target)
    gh.create_issue = AsyncMock(return_value={"number": 999})
    return gh


class TestParentDetection:
    async def test_finds_the_parent_of_a_sub_task(self):
        gh = _github([_issue(86, body="Do a thing\n\nParent: #85")])

        assert await _already_broken_down(gh) == {85}

    async def test_collects_several_parents(self):
        gh = _github([
            _issue(86, body="Parent: #85"),
            _issue(87, body="Parent: #85"),
            _issue(90, body="Parent: #79"),
        ])

        assert await _already_broken_down(gh) == {85, 79}

    async def test_a_closed_sub_task_still_counts(self):
        """A finished breakdown must not be redone — that is the whole point."""
        child = _issue(86, body="Parent: #85")
        child["state"] = "closed"
        gh = _github([child])

        assert await _already_broken_down(gh) == {85}

    async def test_asks_for_closed_issues_too(self):
        gh = _github([])

        await _already_broken_down(gh)

        assert gh.get_issues.await_args.kwargs["state"] == "all"

    async def test_no_children_means_nothing_broken_down(self):
        assert await _already_broken_down(_github([])) == set()

    async def test_a_body_without_a_marker_is_ignored(self):
        gh = _github([_issue(86, body="A task with no parent reference")])

        assert await _already_broken_down(gh) == set()

    async def test_a_missing_body_does_not_raise(self):
        gh = _github([{"number": 86, "title": "t", "body": None, "labels": []}])

        assert await _already_broken_down(gh) == set()

    @pytest.mark.parametrize("body", [
        "Parent: #85",
        "Parent:#85",
        "Parent:  #85",
        "Acceptance criteria:\n- [ ] x\n\nParent: #85",
        "Parent: #85\n",
    ])
    async def test_marker_spellings_that_must_match(self, body):
        assert await _already_broken_down(_github([_issue(86, body=body)])) == {85}

    async def test_does_not_confuse_85_with_850(self):
        gh = _github([_issue(86, body="Parent: #850")])

        assert await _already_broken_down(gh) == {850}


class TestOneCallNotOnePerIssue:
    async def test_detection_costs_a_single_listing(self):
        """Listing issues one at a time is the cost cb2e572 already removed."""
        gh = _github([_issue(86, body="Parent: #85")])

        await _already_broken_down(gh)

        assert gh.get_issues.await_count == 1


class TestTargetedBreakdownSkipsWhenAlreadySplit:
    async def test_an_issue_with_sub_tasks_is_not_broken_down_again(self):
        target = _issue(85)
        gh = _github([_issue(86, body="Parent: #85")], target=target)
        claude = AsyncMock()

        result = await breakdown_stories({
            "github": gh, "claude": claude, "target_issue": 85, "context": "",
        })

        assert result["result"] == "No issues to break down"
        claude.run.assert_not_awaited()
        gh.create_issue.assert_not_awaited()

    async def test_an_issue_without_sub_tasks_is_still_broken_down(self):
        target = _issue(85)
        gh = _github([_issue(86, body="Parent: #79")], target=target)
        claude = AsyncMock()
        claude.run.return_value = type("R", (), {
            "text": '[{"title": "T", "body": "B", "labels": ["role:dev"]}]',
            "total_tokens": 10, "cost_usd": 0.01,
        })()

        await breakdown_stories({
            "github": gh, "claude": claude, "target_issue": 85, "context": "",
        })

        claude.run.assert_awaited_once()
        gh.create_issue.assert_awaited()
