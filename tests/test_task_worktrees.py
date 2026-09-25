"""One git worktree per Dev task (V2 runtime, M5b).

Two tasks in one clone used to reset and check out over each other: cycles
16f3b8af2cca and 2878898cc504 both committed real work and neither opened a
PR. Each task now gets `<clone>/.worktrees/<branch>`; the clone itself stays
on main. Real repositories throughout: the point is what git does.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from theswarm.tools import git as git_ops

IDENTITY = ["-c", "user.name=t", "-c", "user.email=t@t"]


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    """A bare origin with one commit on main, and a clone of it."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(seed))
    (seed / "app.py").write_text("value = 1\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-qm", "base")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")
    workspace = tmp_path / "ws"
    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    git_ops.exclude_locally(str(workspace))
    return workspace


def _branch_of(path) -> str:
    return _git(path, "rev-parse", "--abbrev-ref", "HEAD")


# ── Paths ──────────────────────────────────────────────────────────────


def test_a_worktree_path_leads_back_to_its_clone():
    root = os.path.join("/ws", "repo")
    path = git_ops.worktree_path(root, "feat/issue-12-thing")

    assert path == os.path.join(root, ".worktrees", "feat--issue-12-thing")
    assert git_ops.workspace_root(path) == root
    assert git_ops.workspace_root(root) == root


def test_the_target_venv_of_a_worktree_is_the_clones():
    from theswarm.agents.base import TARGET_VENV_DIR, target_venv_python, venv_home

    root = os.path.join("/ws", "repo")
    task = git_ops.worktree_path(root, "feat/x")

    assert venv_home(task) == root
    assert target_venv_python(task) == os.path.join(root, TARGET_VENV_DIR, "bin", "python")


def test_claude_in_a_worktree_gets_the_clones_venv(tmp_path):
    from theswarm.tools.claude import TARGET_VENV_DIR, _child_env

    root = tmp_path / "repo"
    (root / TARGET_VENV_DIR / "bin").mkdir(parents=True)
    task = Path(git_ops.worktree_path(str(root), "feat/x"))
    task.mkdir(parents=True)

    env = _child_env(workdir=str(task))

    assert env["VIRTUAL_ENV"] == str(root / TARGET_VENV_DIR)


# ── The worktree itself ────────────────────────────────────────────────


async def test_a_task_gets_its_own_checkout_and_the_clone_stays_on_main(clone):
    path = await git_ops.add_worktree(str(clone), "feat/issue-1-a")

    assert Path(path).is_dir()
    assert _branch_of(path) == "feat/issue-1-a"
    assert _branch_of(clone) == "main"
    assert (Path(path) / "app.py").read_text() == "value = 1\n"


async def test_two_tasks_two_branches_no_commit_lost(clone):
    """The regression of 16f3b8af2cca / 2878898cc504."""
    a, b = await asyncio.gather(
        git_ops.add_worktree(str(clone), "feat/issue-1-a"),
        git_ops.add_worktree(str(clone), "feat/issue-2-b"),
    )
    Path(a, "a.py").write_text("a = 1\n")
    Path(b, "b.py").write_text("b = 1\n")

    assert await git_ops.commit_all(a, "feat: a")
    assert await git_ops.commit_all(b, "feat: b")

    assert not Path(a, "b.py").exists() and not Path(b, "a.py").exists()
    assert "a.py" in _git(clone, "show", "--name-only", "--format=", "feat/issue-1-a")
    assert "b.py" in _git(clone, "show", "--name-only", "--format=", "feat/issue-2-b")
    # The clone's own checkout saw none of it, worktrees included.
    assert _git(clone, "status", "--porcelain") == ""


async def test_a_worktree_pushes_its_branch(clone):
    path = await git_ops.add_worktree(str(clone), "feat/issue-3-c")
    Path(path, "c.py").write_text("c = 1\n")
    await git_ops.commit_all(path, "feat: c")

    await git_ops.push_branch(path, "feat/issue-3-c")

    assert _git(clone, "ls-remote", "--heads", "origin", "feat/issue-3-c")


async def test_a_task_sent_back_resumes_its_remote_branch(clone):
    first = await git_ops.add_worktree(str(clone), "feat/issue-4-d")
    Path(first, "d.py").write_text("d = 1\n")
    await git_ops.commit_all(first, "feat: d")
    await git_ops.push_branch(first, "feat/issue-4-d")
    await git_ops.remove_worktree(first)

    again = await git_ops.add_worktree(str(clone), "feat/issue-4-d", resume=True)

    assert (Path(again) / "d.py").read_text() == "d = 1\n"


async def test_a_resume_whose_branch_is_gone_starts_fresh(clone):
    path = await git_ops.add_worktree(str(clone), "feat/issue-5-gone", resume=True)

    assert _branch_of(path) == "feat/issue-5-gone"
    assert sorted(os.listdir(path)) == [".git", "app.py"]


async def test_a_worktree_left_behind_does_not_block_the_retry(clone):
    """A crash or a timeout leaves the checkout; git refuses a second one."""
    await git_ops.add_worktree(str(clone), "feat/issue-6-e")

    path = await git_ops.add_worktree(str(clone), "feat/issue-6-e")

    assert _branch_of(path) == "feat/issue-6-e"


async def test_retiring_a_worktree_keeps_its_branch(clone):
    path = await git_ops.add_worktree(str(clone), "feat/issue-7-f")
    Path(path, "f.py").write_text("f = 1\n")
    await git_ops.commit_all(path, "feat: f")

    await git_ops.remove_worktree(path)

    assert not Path(path).exists()
    assert "f.py" in _git(clone, "show", "--name-only", "--format=", "feat/issue-7-f")


async def test_removing_the_clone_root_is_a_no_op(clone):
    await git_ops.remove_worktree(str(clone))

    assert Path(clone, "app.py").exists()


async def test_the_end_of_a_dev_loop_prunes_every_worktree(clone):
    await git_ops.add_worktree(str(clone), "feat/issue-8-g")
    await git_ops.add_worktree(str(clone), "feat/issue-9-h")

    assert await git_ops.prune_worktrees(str(clone)) == 2
    assert os.listdir(Path(clone, git_ops.WORKTREES_DIR)) == []


async def test_a_clone_left_on_a_task_branch_is_put_back_on_main(clone):
    """The in-place flow before M5b left the clone on the last task's branch."""
    _git(clone, "checkout", "-q", "-b", "feat/old-flow")

    path = await git_ops.add_worktree(str(clone), "feat/issue-10-i")

    assert _branch_of(clone) == "main"
    assert _branch_of(path) == "feat/issue-10-i"


# ── The Dev works where its task lives ────────────────────────────────


async def test_the_dev_implements_commits_and_opens_the_pr_from_its_worktree(clone, monkeypatch):
    from types import SimpleNamespace

    from theswarm.agents import dev

    monkeypatch.setenv("SWARM_DEV_WORKTREES", "1")
    seen: dict = {}

    class Claude:
        async def run(self, prompt, *, workdir=None, **_kw):
            seen["workdir"] = workdir
            Path(workdir, "feature.py").write_text("feature = True\n")
            return SimpleNamespace(
                text="done", total_tokens=10, cost_usd=0.01, structured=None,
            )

    class GitHub:
        async def get_issue_comments(self, number):
            return []

        async def get_pull_requests(self, state="open"):
            return []

        async def create_pr(self, *, branch, base, title, body):
            seen["pr_branch"] = branch
            return {"number": 42, "url": "https://example/pr/42"}

        async def remove_label(self, *a, **kw):
            return None

        async def add_labels(self, *a, **kw):
            return None

        async def add_comment(self, *a, **kw):
            return None

    monkeypatch.setattr(dev, "_sibling_prs", lambda github, task: asyncio.sleep(0, result=""))
    monkeypatch.setattr(dev, "_changes_requested", lambda github, n: asyncio.sleep(0, result=None))
    monkeypatch.setattr(dev, "_open_pr_for_branch", lambda github, b: asyncio.sleep(0, result=None))
    task = {"number": 11, "title": "Add the feature", "body": "please", "labels": []}
    state = {"task": task, "claude": Claude(), "github": GitHub(), "workspace": str(clone)}

    done = await dev.implement_task(state)

    worktree = done["workspace"]
    assert git_ops.workspace_root(worktree) == str(clone)
    assert seen["workdir"] == worktree
    assert "feature.py" in _git(clone, "show", "--name-only", "--format=", done["branch"])
    assert _branch_of(clone) == "main"

    opened = await dev.open_pull_request({**state, **done})

    assert opened["pr"]["number"] == 42
    assert seen["pr_branch"] == done["branch"]
    assert _git(clone, "ls-remote", "--heads", "origin", done["branch"])
    assert not Path(worktree).exists()
