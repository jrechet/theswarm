"""An approved PR that main has moved past goes back to the Dev, who merges main.

Cycle 9d3174f41829 (2026-09-25, two tasks side by side): #326 merged first,
#325 — approved, on the same files — failed "Pull Request has merge
conflicts" at 07:51 and again at 10:15, and sat open. Retrying the merge
changes nothing; the Dev merging origin/main into the branch does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm.agents import dev, techlead
from theswarm.tools import git as git_ops

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def repos(tmp_path, monkeypatch):
    """origin (bare) with main; `seed` pushes to it; `ws` is the swarm's clone."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    origin, seed, ws = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "ws"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    (seed / "app.py").write_text("a = 1\nb = 2\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")
    _git(tmp_path, "clone", "-q", str(origin), str(ws))
    git_ops.exclude_locally(str(ws))
    return SimpleNamespace(origin=origin, seed=seed, ws=ws)


def _push_feature(repos, content: str, branch: str = "feat/issue-11-x") -> str:
    """The task's PR branch on origin, then main moving on."""
    _git(repos.seed, "checkout", "-q", "-b", branch)
    (repos.seed / "app.py").write_text(content)
    _git(repos.seed, "commit", "-qam", "feature")
    _git(repos.seed, "push", "-q", "origin", branch)
    _git(repos.seed, "checkout", "-q", "main")
    return branch


def _move_main(repos, content: str, other: str | None = None) -> None:
    if other:
        (repos.seed / other).write_text("sibling = True\n")
    else:
        (repos.seed / "app.py").write_text(content)
    _git(repos.seed, "add", "-A")
    _git(repos.seed, "commit", "-qm", "sibling merged")
    _git(repos.seed, "push", "-q", "origin", "main")


# ── git ────────────────────────────────────────────────────────────────


async def test_a_clean_merge_of_main_leaves_nothing_to_resolve(repos):
    branch = _push_feature(repos, "a = 1\nb = 3\n")
    _move_main(repos, "", other="sibling.py")
    path = await git_ops.add_worktree(str(repos.ws), branch, resume=True)

    assert await git_ops.merge_main(path) == []
    assert Path(path, "sibling.py").exists() and "b = 3" in Path(path, "app.py").read_text()


async def test_a_conflicting_merge_names_its_files(repos):
    branch = _push_feature(repos, "a = 1\nb = 3\n")
    _move_main(repos, "a = 1\nb = 4\n")
    path = await git_ops.add_worktree(str(repos.ws), branch, resume=True)

    assert await git_ops.merge_main(path) == ["app.py"]
    assert "<<<<<<<" in Path(path, "app.py").read_text()


# ── The TechLead sends it back ─────────────────────────────────────────


class _GitHub:
    def __init__(self):
        self.comments: dict[int, list[str]] = {}
        self.labels: dict[int, set[str]] = {}

    async def get_open_prs(self):
        return [{"number": 325, "head": "feat/issue-323-x", "title": "[#323] Stats", "body": "Closes #323"}]

    async def merge_pr(self, number, merge_method="squash"):
        raise RuntimeError('Pull Request has merge conflicts: 405 {"message": "Pull Request has merge conflicts"}')

    async def delete_branch(self, branch):
        return None

    async def get_issue_comments(self, number):
        return [{"body": b} for b in self.comments.get(number, [])]

    async def add_comment(self, number, body):
        self.comments.setdefault(number, []).append(body)

    async def add_labels(self, number, labels):
        self.labels.setdefault(number, set()).update(labels)

    async def remove_label(self, number, label):
        self.labels.setdefault(number, set()).discard(label)


async def test_an_unmergeable_approved_pr_goes_back_with_the_conflict_marker():
    github = _GitHub()
    state = {"github": github, "github_repo": "o/r",
             "reviews": [{"pr_number": 325, "decision": "APPROVE"}]}

    out = await techlead.merge_approved_prs(state)

    assert out["conflicted_prs"] == [325] and out["merged_prs"] == []
    (note,) = github.comments[323]
    assert techlead.CONFLICT_MARKER in note and techlead.CHANGES_MARKER in note
    assert "PR #325 (branch `feat/issue-323-x`)" in note
    assert "status:ready" in github.labels[323]


async def test_another_merge_failure_is_not_a_conflict():
    github = _GitHub()

    async def outage(number, merge_method="squash"):
        raise RuntimeError("502 Bad Gateway")

    github.merge_pr = outage
    out = await techlead.merge_approved_prs(
        {"github": github, "github_repo": "o/r", "reviews": [{"pr_number": 325, "decision": "APPROVE"}]},
    )

    assert out["conflicted_prs"] == [] and github.comments == {}


def test_the_state_declares_the_conflicted_prs():
    from theswarm.config import AgentState

    assert "conflicted_prs" in AgentState.__annotations__


# ── The Dev merges main first ──────────────────────────────────────────


async def test_the_note_says_it_is_a_conflict():
    github = _GitHub()
    await techlead._send_back_to_dev(
        github, {"number": 325, "head": "feat/issue-323-x", "title": "[#323] Stats"},
        techlead.CONFLICT_SUMMARY, [], conflict=True,
    )

    note = await dev._changes_requested(github, 323)

    assert note["conflict"] is True and note["branch"] == "feat/issue-323-x"
    assert techlead.CONFLICT_MARKER not in note["text"]


def _dev_state(repos, branch, claude):
    github = _GitHub()
    github.comments[11] = [techlead.CONFLICT_MARKER + "\n" + techlead._changes_comment(
        {"number": 30, "head": branch}, techlead.CONFLICT_SUMMARY, [],
    )]
    task = {"number": 11, "title": "Add x", "body": "", "labels": []}
    return {"task": task, "claude": claude, "github": github, "workspace": str(repos.ws)}


async def test_a_clean_merge_needs_no_claude_call(repos, monkeypatch):
    monkeypatch.setenv("SWARM_DEV_WORKTREES", "1")
    monkeypatch.setattr(dev, "_sibling_prs", AsyncMock(return_value=""))
    branch = _push_feature(repos, "a = 1\nb = 3\n")
    _move_main(repos, "", other="sibling.py")
    claude = SimpleNamespace(run=AsyncMock())

    done = await dev.implement_task(_dev_state(repos, branch, claude))

    assert claude.run.await_count == 0
    assert done["result"] == "merged main into the branch"
    assert done["branch"] == branch and done["diff_stat"]


async def test_real_conflicts_go_to_claude_by_name(repos, monkeypatch):
    monkeypatch.setenv("SWARM_DEV_WORKTREES", "1")
    monkeypatch.setattr(dev, "_sibling_prs", AsyncMock(return_value=""))
    branch = _push_feature(repos, "a = 1\nb = 3\n")
    _move_main(repos, "a = 1\nb = 4\n")
    seen: dict = {}

    async def resolve(prompt, *, workdir=None, **_kw):
        seen["prompt"] = prompt
        Path(workdir, "app.py").write_text("a = 1\nb = 4\nc = 3\n")
        return SimpleNamespace(text="resolved", total_tokens=5, cost_usd=0.01, structured=None, backend="sdk")

    done = await dev.implement_task(_dev_state(repos, branch, SimpleNamespace(run=resolve)))

    assert "## Merge conflicts to resolve first" in seen["prompt"] and "- app.py" in seen["prompt"]
    worktree = done["workspace"]
    assert "<<<<<<<" not in Path(worktree, "app.py").read_text()
    # The resolution concluded the merge: main is an ancestor of the branch.
    subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=worktree, check=True)
