"""`commit_all` answers "did *we* commit", not "is there work".

Local cycle targeted-161-20260919T143555Z, task #161: Claude runs with
`acceptEdits` and a Bash allowlist, so it committed, pushed and opened
PR #165 itself at 16:39. At 16:46 this harness called `commit_all`, got
"Nothing to commit", and concluded `no file changes produced` — it filed
a failed-attempt note on the issue (which pushes the task behind its
siblings next cycle), skipped `open_pr`, and the cycle reported `prs []`
while the PR sat open on GitHub.

The tree was already the truth for an in-place edit (#125). The branch is
the truth for a commit someone else made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from theswarm.agents.dev import ATTEMPT_MARKER, _should_open_pr, implement_task

TASK = {"number": 161, "title": "Flag a harness run as a regression", "body": "Do it."}
CLAUDE_COMMITTED_ITSELF = (
    "I implemented the change, committed it on the feature branch and "
    "opened a pull request."
)
DIFF_AGAINST_MAIN = (
    " scripts/cycle_e2e.py            | 71 ++++++++--\n"
    " tests/test_cycle_e2e_harness.py | 91 +++++++++++++\n"
    " 2 files changed, 142 insertions(+), 1 deletion(-)"
)


def _github() -> AsyncMock:
    gh = AsyncMock()
    gh.add_comment = AsyncMock()
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    gh.get_issues = AsyncMock(return_value=[])
    gh.get_open_prs = AsyncMock(return_value=[])
    gh.get_pr_files = AsyncMock(return_value=[])
    gh.get_issue_comments = AsyncMock(return_value=[])
    return gh


def _claude(text: str = CLAUDE_COMMITTED_ITSELF) -> AsyncMock:
    claude = AsyncMock()
    claude.run = AsyncMock(
        return_value=SimpleNamespace(text=text, total_tokens=5, cost_usd=0.01),
    )
    return claude


async def _implement(tmp_path, github):
    """Run implement_task where Claude committed before we looked."""
    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
         patch("theswarm.tools.git.get_diff_stat",
               new=AsyncMock(return_value=DIFF_AGAINST_MAIN)):
        return await implement_task({
            "task": TASK, "claude": _claude(), "workspace": str(tmp_path),
            "github": github,
        })


async def test_work_committed_by_claude_still_reaches_the_pr_node(tmp_path):
    result = await _implement(tmp_path, _github())

    assert result.get("diff_stat"), (
        "the branch carries 142 changed lines; an empty diff_stat sends "
        "_should_open_pr to 'end' and the cycle reports no PR"
    )
    assert _should_open_pr({**result, "branch": result.get("branch")}) == "open_pr"


async def test_no_false_failed_attempt_note_when_the_branch_has_work(tmp_path):
    github = _github()

    await _implement(tmp_path, github)

    notes = [
        call.args[1] for call in github.add_comment.call_args_list
        if len(call.args) > 1 and ATTEMPT_MARKER in str(call.args[1])
    ]
    assert not notes, (
        "a failed-attempt note pushes this task behind its untried siblings "
        f"next cycle; the attempt succeeded. Got: {notes}"
    )


async def test_a_genuinely_empty_branch_is_still_reported_as_no_changes(tmp_path):
    """The guard must not swallow the real "Claude produced nothing" case."""
    github = _github()

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
         patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="")):
        result = await implement_task({
            "task": TASK, "claude": _claude("I could not do it."),
            "workspace": str(tmp_path), "github": github,
        })

    assert result.get("result") == "no changes produced"
    assert not result.get("diff_stat")
