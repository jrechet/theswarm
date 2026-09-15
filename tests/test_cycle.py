"""Test that the stub cycle runs end-to-end without errors."""

from unittest.mock import patch

import pytest

from theswarm import cycle as cycle_mod
from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle
from theswarm.token_counter import TokenTracker


async def test_stub_cycle_runs():
    """The full cycle should complete with zero tokens in stub mode."""
    config = CycleConfig(github_repo="", team_id="test")
    result = await run_daily_cycle(config)
    assert result["tokens"] == 0
    assert result["cost_usd"] == 0.0
    assert result["demo_report"] is not None


def test_token_tracker():
    tracker = TokenTracker()
    tracker.record("dev", 100_000, cost_usd=0.30)
    tracker.record("qa", 50_000, cost_usd=0.15)
    assert tracker.total_tokens == 150_000
    assert tracker.total_cost == pytest.approx(0.45, abs=0.01)


# ── Story #85: an already-satisfied sub-task closes instead of looping ──


class _FakeGitHub:
    """Just enough of GitHubClient for `_close_already_satisfied` and
    `_requeue_unfinished` to operate against."""

    def __init__(self, issues: list[dict] | None = None) -> None:
        self.issues = {i["number"]: i for i in (issues or [])}
        self.closed: list[tuple[int, str]] = []
        self.label_ops: list[tuple[str, int, object]] = []

    async def close_issue(self, number: int, comment: str | None = None) -> None:
        self.closed.append((number, comment or ""))
        if number in self.issues:
            self.issues[number]["state"] = "closed"

    async def remove_label(self, number: int, label: str) -> None:
        self.label_ops.append(("remove", number, label))
        labels = self.issues.get(number, {}).get("labels")
        if labels and label in labels:
            labels.remove(label)

    async def add_labels(self, number: int, labels: list[str]) -> None:
        self.label_ops.append(("add", number, tuple(labels)))
        if number in self.issues:
            self.issues[number]["labels"] = list(
                set(self.issues[number].get("labels", [])) | set(labels)
            )

    async def get_issues(self, labels=None, state: str = "open") -> list[dict]:
        out = []
        for issue in self.issues.values():
            if issue.get("state", "open") != state:
                continue
            if labels and not set(labels) <= set(issue.get("labels", [])):
                continue
            out.append(issue)
        return sorted(out, key=lambda i: i["number"])


def _graph_returning(states: list[dict]):
    """Dev graph stub yielding one state per iteration (mirrors
    tests/test_dev_loop_no_progress_guards.py)."""
    calls = {"n": 0}

    class _Stub:
        async def ainvoke(self, _state):
            index = min(calls["n"], len(states) - 1)
            calls["n"] += 1
            return states[index]

    return lambda: _Stub(), calls


async def test_already_satisfied_task_closes_and_loop_continues_to_next_task():
    """A no-PR outcome carrying `already_satisfied` evidence must close the
    issue and keep going — not end the loop or burn the "twice without a
    PR" allowance meant for genuine failures."""
    fake_github = _FakeGitHub()
    factory, calls = _graph_returning([
        {
            "task": {"number": 173},
            "already_satisfied": "src/routers/concerts.py — artist_name filter added in #235",
        },
        {"task": {"number": 174}, "pr": {"number": 5, "url": "https://example/pr/5"}},
        {"task": None},
    ])

    orig_build_base_state = cycle_mod._build_base_state

    def _base_state_with_github(config):
        state = orig_build_base_state(config)
        state["github"] = fake_github
        return state

    with patch.object(cycle_mod, "build_dev_graph", factory), \
         patch.object(cycle_mod, "_build_base_state", _base_state_with_github):
        result = await run_daily_cycle(CycleConfig(github_repo=""))

    # All three iterations ran — the already-satisfied outcome did not end
    # the loop, it moved on to the next ready task.
    assert calls["n"] == 3

    # #173 was closed exactly once, with a comment naming the evidence.
    assert len(fake_github.closed) == 1
    closed_number, comment = fake_github.closed[0]
    assert closed_number == 173
    assert "src/routers/concerts.py" in comment

    assert ("remove", 173, "status:in-progress") in fake_github.label_ops

    # The second, genuinely-ready task still produced its PR in the same run.
    assert [p["number"] for p in result["prs"]] == [5]


async def test_genuinely_failed_task_still_requeues_after_two_attempts():
    """No `already_satisfied` marker: unchanged behavior — two no-PR
    attempts end the loop and `_requeue_unfinished` hands the task back."""
    fake_github = _FakeGitHub([
        {
            "number": 173,
            "labels": ["role:dev", "status:in-progress"],
            "body": "Parent: #99",
            "state": "open",
        },
    ])
    factory, calls = _graph_returning([{"task": {"number": 173}}])  # never a PR

    with patch.object(cycle_mod, "build_dev_graph", factory), \
         patch("theswarm.tools.github.GitHubClient", return_value=fake_github):
        await run_daily_cycle(CycleConfig(github_repo="", target_issue=99))

    # One retry, then the existing "twice without a PR" stop — unchanged.
    assert calls["n"] == 2
    assert fake_github.closed == []

    # _requeue_unfinished put it back to status:ready.
    assert ("add", 173, ("status:ready",)) in fake_github.label_ops
    assert ("remove", 173, "status:in-progress") in fake_github.label_ops
