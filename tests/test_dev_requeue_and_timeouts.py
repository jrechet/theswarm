"""A failed implementation must requeue its task and get realistic time.

Endurance run findings (cycles 9a827ae98879 and 7f0e4b24bfa8): 13 ready
issues drained in two cycles with zero PRs. Two compounding defects:

- ClaudeCLI's 180s default was calibrated for prompts that "finished in
  <90s"; a real feature (route + template + tests) regularly runs past it,
  so every substantial task died in 'CLI timed out after 180s'.
- When an iteration failed, cycle.py's retry re-ran the whole dev graph and
  pick_task grabbed a *different* issue, leaving the failed one orphaned in
  status:in-progress — each failure consumed two issues from the backlog.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from theswarm.agents.dev import (
    IMPLEMENT_TIMEOUT_SECONDS,
    implement_task,
    retry_implement,
)
from theswarm.cycle import PHASE_TIMEOUTS


class _FakeGithub:
    def __init__(self) -> None:
        self.added: list[tuple[int, list[str]]] = []
        self.removed: list[tuple[int, str]] = []

    async def add_labels(self, number, labels):
        self.added.append((number, list(labels)))

    async def remove_label(self, number, label):
        self.removed.append((number, label))


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


def _state(workspace, claude, github):
    return {
        "task": {"number": 159, "title": "Create dashboard template", "body": "..."},
        "claude": claude,
        "workspace": workspace,
        "github": github,
        "context": "",
    }


async def test_implementation_gets_more_than_the_cli_default(tmp_path):
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="", total_tokens=0, cost_usd=0.0)

    await implement_task(_state(await _git_workspace(tmp_path), claude, _FakeGithub()))

    assert claude.run.call_args.kwargs["timeout"] == IMPLEMENT_TIMEOUT_SECONDS
    assert IMPLEMENT_TIMEOUT_SECONDS > 180


async def test_failed_implementation_requeues_the_task(tmp_path):
    claude = AsyncMock()
    claude.run.side_effect = RuntimeError("CLI timed out after 420s")
    github = _FakeGithub()

    with pytest.raises(RuntimeError):
        await implement_task(_state(await _git_workspace(tmp_path), claude, github))

    assert (159, ["status:ready"]) in github.added
    assert (159, "status:in-progress") in github.removed


async def test_phase_timeout_cancellation_also_requeues(tmp_path):
    """A dev_iter phase abort cancels the coroutine — the task must still return."""
    claude = AsyncMock()

    async def hang(*_a, **_kw):
        await asyncio.sleep(60)

    claude.run = hang
    github = _FakeGithub()

    task = asyncio.ensure_future(implement_task(_state(await _git_workspace(tmp_path), claude, github)))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert (159, ["status:ready"]) in github.added


async def test_successful_implementation_does_not_requeue(tmp_path):
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="", total_tokens=10, cost_usd=0.01)
    github = _FakeGithub()

    await implement_task(_state(await _git_workspace(tmp_path), claude, github))

    assert github.added == []
    assert github.removed == []


async def test_ralph_retry_gets_the_same_budget(tmp_path):
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="", total_tokens=0, cost_usd=0.0)

    await retry_implement({
        "task": {"number": 159, "title": "t"},
        "claude": claude,
        "workspace": str(tmp_path),
        "retry_count": 0,
        "test_output": "boom",
    })

    assert claude.run.call_args.kwargs["timeout"] == IMPLEMENT_TIMEOUT_SECONDS


def test_dev_iter_phase_budget_fits_the_success_path():
    """implement + cold install + tests + one repair round must fit."""
    success_path = IMPLEMENT_TIMEOUT_SECONDS + 300 + 120 + IMPLEMENT_TIMEOUT_SECONDS + 120
    assert PHASE_TIMEOUTS["dev_iter"] >= success_path
