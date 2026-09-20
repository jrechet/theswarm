"""An approval guessed from prose is not an approval.

`_salvage_decision` exists so a verdict written in markdown is not thrown
away for its shape, and its own docstring draws the line: "guessing an
approval from a friendly tone would merge code nobody signed off on". The
salvage path honoured that for REQUEST_CHANGES — which is never overridden
once salvaged — and ignored it for APPROVE.

Local cycle targeted-161-20260919T143555Z showed why it matters. The
reviewer's `claude -p` call inherited the host's own session instructions
and answered them instead of the review prompt:

    Could not parse review JSON (decision read as APPROVE): "This session
    was a **read-only code review** of PR #166 (I did not write, edit, or
    commit any code) — several steps in that wrap-up template don't apply
    here, so I'm not going to fabricate a deploy or…"

A stray APPROVE line inside an answer that was not about the PR became a
sign-off on it. Cleaning the host's configuration removes that particular
contamination; it does not make a guessed approval trustworthy.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from theswarm.agents.techlead import _review_single_pr

PR = {"number": 166, "title": "fix(agents): a failed install is not a red suite", "body": ""}

OFF_TOPIC_WITH_A_STRAY_VERDICT = """\
This session was a **read-only code review** of PR #166 (I did not write,
edit, or commit any code) — several steps in that wrap-up template don't
apply here, so I'm not going to fabricate a deploy or a production check.

APPROVE
"""

STRUCTURED_APPROVAL = """\
```json
{"decision": "APPROVE", "summary": "Reads well, tests cover the case.", "issues": []}
```
"""


def _github() -> AsyncMock:
    gh = AsyncMock()
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.add_comment = AsyncMock()
    gh.create_pr_review = AsyncMock()
    return gh


def _claude(text: str) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(
        return_value=SimpleNamespace(text=text, total_tokens=10, cost_usd=0.01),
    )
    return claude


async def test_an_approval_salvaged_from_prose_is_not_filed_as_one():
    review = await _review_single_pr(
        _github(), _claude(OFF_TOPIC_WITH_A_STRAY_VERDICT), PR, "",
    )

    assert review["decision"] != "APPROVE", (
        "a bare APPROVE inside unstructured prose is a guess, not a "
        "sign-off; filing it as one approves code nobody reviewed"
    )


async def test_the_prose_still_reaches_the_pull_request():
    """Downgrading the verdict must not hide what the reviewer said."""
    gh = _github()

    await _review_single_pr(gh, _claude(OFF_TOPIC_WITH_A_STRAY_VERDICT), PR, "")

    written = " ".join(
        str(call.args) + str(call.kwargs)
        for call in (gh.create_pr_review.call_args_list + gh.add_comment.call_args_list)
    )
    assert "read-only code review" in written


async def test_a_structured_approval_is_still_an_approval():
    review = await _review_single_pr(
        _github(), _claude(STRUCTURED_APPROVAL), PR, "",
    )

    assert review["decision"] == "APPROVE"


LABELLED_APPROVAL_IN_PROSE = """\
I cross-checked the diff against the pre-PR source and ran the suite.

**Decision: APPROVE** — the regression test covers the reported case.
"""


async def test_a_labelled_verdict_in_prose_is_still_a_verdict():
    """#104 settled this: a markdown verdict is not thrown away for its shape.

    The line is between a reviewer *stating* a verdict and an answer that
    merely contains the word.
    """
    review = await _review_single_pr(
        _github(), _claude(LABELLED_APPROVAL_IN_PROSE), PR, "",
    )

    assert review["decision"] == "APPROVE"
