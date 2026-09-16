"""A review is submitted as what it is.

The submit step mapped anything that was not APPROVE to REQUEST_CHANGES —
so a review the parser had filed as COMMENT went up as REQUEST_CHANGES,
GitHub refused it (one cannot request changes on one's own PR), and the
fallback comment on PR #104 was headed "(REQUEST_CHANGES)" above a body
whose first words were "Decision: APPROVE".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from theswarm.agents.techlead import _review_single_pr


def _github(*, refuse_reviews: bool = False) -> AsyncMock:
    gh = AsyncMock()
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.add_comment = AsyncMock()
    if refuse_reviews:
        gh.create_pr_review = AsyncMock(
            side_effect=RuntimeError("422 Review Can not approve your own pull request"),
        )
    else:
        gh.create_pr_review = AsyncMock()
    return gh


def _claude(text: str) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(text=text, total_tokens=10, cost_usd=0.01))
    return claude


PR = {"number": 104, "title": "[#89] Add e2e regression test", "body": ""}


async def test_a_markdown_approval_is_submitted_as_an_approval():
    gh = _github()

    review = await _review_single_pr(
        gh, _claude("**Decision: APPROVE**\n\nI cross-checked the diff."), PR, "",
    )

    assert review["decision"] == "APPROVE"
    assert gh.create_pr_review.await_args.kwargs["event"] == "APPROVE"


async def test_a_comment_goes_up_as_a_comment_not_a_change_request():
    gh = _github()

    review = await _review_single_pr(gh, _claude("Interesting approach, a few thoughts."), PR, "")

    assert review["decision"] == "COMMENT"
    assert gh.create_pr_review.await_args.kwargs["event"] == "COMMENT"


async def test_when_github_refuses_the_fallback_comment_is_headed_with_the_real_verdict():
    gh = _github(refuse_reviews=True)

    review = await _review_single_pr(
        gh, _claude("**Decision: APPROVE**\n\nSolid."), PR, "",
    )

    assert review["decision"] == "APPROVE"
    body = gh.add_comment.await_args.args[1]
    assert body.startswith("**Tech Lead Review** (APPROVE)")


async def test_json_reviews_are_unchanged():
    gh = _github()

    review = await _review_single_pr(
        gh, _claude('{"decision": "APPROVE", "summary": "ok", "issues": []}'), PR, "",
    )

    assert review["decision"] == "APPROVE"
    assert gh.create_pr_review.await_args.kwargs["event"] == "APPROVE"


async def test_a_change_request_salvaged_from_prose_is_not_overridden_to_approve():
    """PR #117: the prose said REQUEST_CHANGES, the structured issue list was
    empty because prose has none, and the MVP override approved it."""
    gh = _github()

    review = await _review_single_pr(
        gh, _claude("**Decision: REQUEST_CHANGES**\n\nThe list route drops the limit."), PR, "",
    )

    assert review["decision"] == "REQUEST_CHANGES"
    assert gh.create_pr_review.await_args.kwargs["event"] == "REQUEST_CHANGES"


async def test_a_json_change_request_without_issues_still_gets_the_mvp_override():
    gh = _github()

    review = await _review_single_pr(
        gh, _claude('{"decision": "REQUEST_CHANGES", "summary": "meh", "issues": []}'), PR, "",
    )

    assert review["decision"] == "APPROVE"


async def test_a_salvaged_review_is_posted_as_its_own_prose():
    """Not the template: that cut the reasoning at 500 characters and signed
    off "No issues found. Code looks good." under a change request."""
    gh = _github(refuse_reviews=True)
    prose = "**Decision: REQUEST_CHANGES**\n\nThe merge sort compares timestamps " \
            "from two sources with inconsistent timezone semantics." + " More detail." * 60

    await _review_single_pr(gh, _claude(prose), PR, "")

    body = gh.add_comment.await_args.args[1]
    assert "No issues found" not in body
    assert "inconsistent timezone semantics" in body
    assert body.count("More detail.") == 60  # not truncated at 500
