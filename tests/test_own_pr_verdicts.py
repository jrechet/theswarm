"""The swarm reviews its own PRs: GitHub takes only a COMMENT review there.

It opens and reviews with one identity, and GitHub answers 422 "Can not
approve your own pull request" to every APPROVE and REQUEST_CHANGES —
ten warnings in Seq on 2026-09-25, each followed by an issue comment.
Learned once per process; the verdict goes as a COMMENT review, with the
decision in its body and in the theswarm/review status.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock


from theswarm.agents import techlead


class _GitHub:
    def __init__(self, refuse: str = "Can not approve your own pull request"):
        self.refuse = refuse
        self.reviews: list[tuple[str, str]] = []
        self.comments: list[str] = []

    async def get_pr_files(self, number):
        return [{"filename": "app.py", "patch": "+x = 1", "status": "modified", "additions": 1, "deletions": 0}]

    async def create_pr_review(self, number, body, event="COMMENT"):
        if event != "COMMENT" and self.refuse:
            raise RuntimeError(f'422 {{"message": "Unprocessable Entity", "errors": ["{self.refuse}"]}}')
        self.reviews.append((event, body))

    async def add_comment(self, number, body):
        self.comments.append(body)


def _claude(decision: str = "APPROVE"):
    verdict = {"decision": decision, "summary": "Looks right.", "issues": []}
    return SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(
        text="", structured=verdict, total_tokens=5, cost_usd=0.01, backend="sdk",
    )))


PR = {"number": 41, "title": "[#11] Stats", "head": "feat/x", "body": "Closes #11"}


async def test_a_refused_approve_becomes_a_comment_review_with_the_decision():
    github = _GitHub()

    await techlead._review_single_pr(github, _claude(), PR, "")

    ((event, body),) = github.reviews
    assert event == "COMMENT" and "**Decision: APPROVE**" in body
    assert github.comments == []  # a review, not an issue comment
    assert techlead._OWN_PR_VERDICTS_REFUSED is True


async def test_once_learned_the_verdict_goes_straight_to_a_comment_review():
    github = _GitHub()
    await techlead._review_single_pr(github, _claude(), PR, "")
    calls_before = len(github.reviews)

    tries: list[str] = []
    original = github.create_pr_review

    async def counting(number, body, event="COMMENT"):
        tries.append(event)
        await original(number, body, event)

    github.create_pr_review = counting
    await techlead._review_single_pr(github, _claude(), {**PR, "number": 42}, "")

    assert tries == ["COMMENT"]
    assert len(github.reviews) == calls_before + 1


async def test_another_refusal_still_falls_back_to_an_issue_comment():
    github = _GitHub(refuse="Validation Failed")

    await techlead._review_single_pr(github, _claude(), PR, "")

    assert github.reviews == [] and len(github.comments) == 1
    assert techlead._OWN_PR_VERDICTS_REFUSED is False


async def test_a_plain_comment_verdict_is_untouched():
    github = _GitHub()

    await techlead._review_single_pr(github, _claude("COMMENT"), PR, "")

    ((event, body),) = github.reviews
    assert event == "COMMENT" and "**Decision:" not in body
