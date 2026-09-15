"""End-to-end regression test for story #85: an already-satisfied targeted
child must close instead of looping.

Reproduces the exact scenario from the bug report: a cycle targeted at
parent #230 whose children are #233 (tests+filter, done), #234 (UI, done)
and #232 (filter — already implemented by #233's PR). Pre-fix, implement_task
saw zero files written for #232, called it "no changes produced" and left it
`status:in-progress`; the dev loop's tie-break (least-tried, then
ready-before-in-progress — dev.py `_pick_targeted`) re-selected the very same
task the moment its untried sibling ran out of first attempts, and
`_requeue_unfinished` handed it back to `status:ready` at the end of the
cycle for the next one to trip over the same way.

Exercises the real `pick_task` / `implement_task` nodes (dev.py) and the real
`_requeue_unfinished` (cycle.py) against a fake GitHubClient — the dev-loop
portion directly, per the story's own acceptance criteria, rather than the
full `run_daily_cycle` (PO/TechLead breakdown, quality gates, PR — none of
which this bug touches).
"""

from __future__ import annotations

from unittest.mock import patch

from theswarm.agents import dev as dev_mod
from theswarm.agents.dev import implement_task, pick_task
from theswarm.config import CycleConfig
from theswarm.cycle import _requeue_unfinished

TARGET_ISSUE = 230

ALREADY_SATISFIED_TEXT = (
    "Investigated #232 before writing anything.\n"
    "ALREADY_SATISFIED: src/routers/concerts.py — artist_name filter added in #235"
)
NO_CHANGES_TEXT = "Looked at #240, nothing to add yet."


class _Result:
    def __init__(self, text: str, tokens: int = 10, cost: float = 0.01) -> None:
        self.text = text
        self.total_tokens = tokens
        self.cost_usd = cost


class _StubClaude:
    """Hands out one canned response per call, in order."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    async def run(self, prompt, **kwargs):
        return _Result(self._texts.pop(0))


class _FakeGitHub:
    def __init__(self, issues: list[dict]) -> None:
        self.issues = {i["number"]: i for i in issues}
        self.closed: list[tuple[int, str]] = []
        self.label_ops: list[tuple[str, int, object]] = []

    async def get_issue(self, number: int) -> dict | None:
        return self.issues.get(number)

    async def get_issues(self, labels=None, state="open") -> list[dict]:
        out = []
        for issue in self.issues.values():
            if issue.get("state", "open") != state:
                continue
            if labels and not set(labels) <= set(issue.get("labels", [])):
                continue
            out.append(issue)
        return sorted(out, key=lambda i: i["number"])

    async def add_labels(self, number: int, labels: list[str]) -> None:
        self.label_ops.append(("add", number, tuple(labels)))
        self.issues[number]["labels"] = list(
            set(self.issues[number]["labels"]) | set(labels)
        )

    async def remove_label(self, number: int, label: str) -> None:
        self.label_ops.append(("remove", number, label))
        if label in self.issues[number]["labels"]:
            self.issues[number]["labels"].remove(label)

    async def close_issue(self, number: int, comment: str | None = None) -> None:
        self.closed.append((number, comment or ""))
        self.issues[number]["state"] = "closed"


def _issue(number, title, labels, body="", state="open") -> dict:
    return {
        "number": number, "title": title, "labels": list(labels),
        "body": body, "state": state,
    }


def _github() -> _FakeGitHub:
    """Parent #230; #233/#234 already merged, #232 and #240 still open."""
    return _FakeGitHub([
        _issue(TARGET_ISSUE, "Filterable concerts list", ["status:in-progress"],
               body="Add filtering to the concerts list"),
        _issue(233, "Add tests + artist_name filter", ["role:dev"], state="closed",
               body=f"Parent: #{TARGET_ISSUE}"),
        _issue(234, "Add filter UI", ["role:dev"], state="closed",
               body=f"Parent: #{TARGET_ISSUE}"),
        _issue(232, "Add artist_name query filter", ["role:dev", "status:ready"],
               body=f"Filter concerts by artist_name\n\nParent: #{TARGET_ISSUE}"),
        _issue(240, "Add sort order to concerts list", ["role:dev", "status:ready"],
               body=f"Add a sort query param\n\nParent: #{TARGET_ISSUE}"),
    ])


async def _git_workspace(tmp_path) -> str:
    """implement_task branches off main first — give it a real repo."""
    from theswarm.tools.git import _identity_args, _run_git

    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git("init", "-q", "-b", "main", cwd=str(repo))
    (repo / "README.md").write_text("x\n")
    await _run_git("add", "-A", cwd=str(repo))
    await _run_git(*_identity_args(), "commit", "-qm", "init", cwd=str(repo))
    return str(repo)


async def _run_targeted_iterations(github, workspace, claude_texts, count):
    """Replicate cycle.py's dev-loop bookkeeping (cycle.py:479-502): pick a
    targeted task, implement it, and stop once the same task has produced no
    PR twice in a row — exactly what the loop around `build_dev_graph`
    does, minus quality_gates/open_pr which this bug never touches.
    """
    attempted_tasks: list[int] = []
    attempted_without_pr: set[int] = set()
    claude = _StubClaude(claude_texts)
    picked: list[int] = []

    for _ in range(count):
        result = await pick_task({
            "github": github, "target_issue": TARGET_ISSUE,
            "attempted_tasks": attempted_tasks,
        })
        task = result["task"]
        if task is None:
            break
        picked.append(task["number"])

        impl = await implement_task({
            "task": task, "claude": claude, "workspace": workspace,
            "github": github, "context": "",
        })

        if impl.get("pr") is None:
            if task["number"] in attempted_without_pr:
                break
            attempted_without_pr.add(task["number"])

    return {"picked": picked, "attempted_tasks": attempted_tasks}


async def test_already_satisfied_child_closes_and_the_loop_moves_on(tmp_path):
    github = _github()
    workspace = await _git_workspace(tmp_path)

    run = await _run_targeted_iterations(
        github, workspace,
        [ALREADY_SATISFIED_TEXT, NO_CHANGES_TEXT, NO_CHANGES_TEXT],
        count=3,
    )

    # close_issue was called for #232, and the comment names the file.
    assert len(github.closed) == 1
    closed_number, comment = github.closed[0]
    assert closed_number == 232
    assert "src/routers/concerts.py" in comment

    # #232 is never re-added to status:ready.
    assert ("add", 232, ("status:ready",)) not in github.label_ops
    assert "status:ready" not in github.issues[232]["labels"]

    # The loop moved on to the second ready child instead of ending after #232.
    assert run["picked"][:2] == [232, 240]

    # Only one dev iteration was spent on #232 (not two, as in the bug report).
    assert run["attempted_tasks"].count(232) == 1

    # _requeue_unfinished (run once, at the end of the real dev loop) must not
    # touch #232 — it is closed, not claimed-but-unfinished.
    with patch("theswarm.tools.github.GitHubClient", return_value=github):
        requeued = await _requeue_unfinished(
            CycleConfig(github_repo="owner/repo", target_issue=TARGET_ISSUE)
        )
    assert 232 not in requeued
    assert 240 in requeued  # the genuinely unfinished sibling still gets handed back
    assert "status:ready" not in github.issues[232]["labels"]


async def test_reverting_the_fix_reselects_the_same_task(tmp_path):
    """Guards the fix itself: without ALREADY_SATISFIED detection, #232 is
    picked a second time and never closes — the exact story #85 bug."""
    github = _github()
    workspace = await _git_workspace(tmp_path)

    with patch.object(dev_mod, "_extract_already_satisfied", return_value=None):
        run = await _run_targeted_iterations(
            github, workspace,
            [ALREADY_SATISFIED_TEXT, NO_CHANGES_TEXT, NO_CHANGES_TEXT],
            count=3,
        )

    assert github.closed == []  # never closed
    assert run["picked"] == [232, 240, 232]  # #232 re-selected a second time
    assert run["attempted_tasks"].count(232) == 2
