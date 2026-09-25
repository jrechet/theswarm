"""An approved pull request merges only on green CI.

The TechLead merged every APPROVE without reading the PR's CI, and neither
branch protection stops it: TheSwarm's main exempts the admin token the
swarm merges with, and concert-tour-app has no CI and no required check at
all. Red goes back to the Dev with the failing checks named; pending is
waited for, bounded, then left open; a repository without CI merges as
before.

The harness had the same blind spot the other way round: it read the
swarm's own `theswarm/review` status as CI, so concert-tour-app, which has
no workflow, reported "CI green" on every approval and "CI RED" on every
REQUEST_CHANGES (ac30a0a1a126).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from theswarm.agents import ci_gate


def _check(name: str, state: str, summary: str = "") -> dict:
    return {"name": name, "state": state, "summary": summary}


# ── The verdict ────────────────────────────────────────────────────────


def test_a_failed_check_is_red_and_named():
    verdict = ci_gate.ci_verdict([
        _check("tests", "failure", "2 failed"), _check("lint", "success"),
    ])

    assert verdict.state == "red"
    assert [c["name"] for c in verdict.failing] == ["tests"]


def test_the_swarm_s_own_review_status_is_not_ci():
    verdict = ci_gate.ci_verdict([
        _check("theswarm/review", "failure"), _check("tests", "success"),
    ])

    assert verdict.state == "green"


def test_a_running_check_is_pending():
    assert ci_gate.ci_verdict([_check("tests", "in_progress"), _check("lint", "success")]).state == "pending"
    assert ci_gate.ci_verdict([_check("ci/legacy", "pending")]).state == "pending"


def test_no_ci_at_all_is_none():
    assert ci_gate.ci_verdict([]).state == "none"
    assert ci_gate.ci_verdict([_check("theswarm/review", "success")]).state == "none"


def test_cancelled_and_skipped_runs_carry_no_signal():
    assert ci_gate.ci_verdict([_check("tests", "cancelled"), _check("e2e", "skipped")]).state == "none"
    assert ci_gate.ci_verdict([_check("tests", "cancelled"), _check("lint", "success")]).state == "green"


@pytest.mark.parametrize("state", ["error", "timed_out", "action_required", "startup_failure"])
def test_every_failing_conclusion_is_red(state):
    assert ci_gate.ci_verdict([_check("tests", state)]).state == "red"


# ── The wait ───────────────────────────────────────────────────────────


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


class _GitHub:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked: list[str] = []

    async def get_ci_checks(self, ref):
        self.asked.append(ref)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


async def test_pending_is_waited_for_until_green():
    clock = _Clock()
    github = _GitHub([[_check("tests", "queued")], [_check("tests", "in_progress")], [_check("tests", "success")]])

    verdict = await ci_gate.wait_for_ci(github, "abc123", wait_seconds=300, sleep=clock.sleep, clock=clock)

    assert verdict.state == "green"
    assert github.asked == ["abc123"] * 3


async def test_pending_past_the_bound_stays_pending():
    clock = _Clock()
    github = _GitHub([[_check("tests", "in_progress")]])

    verdict = await ci_gate.wait_for_ci(github, "abc123", wait_seconds=60, sleep=clock.sleep, clock=clock)

    assert verdict.state == "pending"
    assert clock.now >= 60


async def test_a_client_without_ci_reading_is_none():
    verdict = await ci_gate.wait_for_ci(SimpleNamespace(), "abc123", wait_seconds=60)

    assert verdict.state == "none"


async def test_an_unreadable_ci_does_not_block_the_merge():
    class Broken:
        async def get_ci_checks(self, ref):
            raise RuntimeError("502 Bad Gateway")

    verdict = await ci_gate.wait_for_ci(Broken(), "abc123", wait_seconds=60)

    assert verdict.state == "none"


async def test_no_sha_is_none():
    verdict = await ci_gate.wait_for_ci(_GitHub([[_check("tests", "failure")]]), "", wait_seconds=60)

    assert verdict.state == "none"


# ── The TechLead's merge ───────────────────────────────────────────────


class _Repo:
    """A GitHub fake for the merge loop."""

    def __init__(self, ci_state: str):
        self.ci_state = ci_state
        self.merged: list[int] = []
        self.comments: list[tuple[int, str]] = []
        self.labels: list[tuple[int, list[str]]] = []

    async def get_open_prs(self):
        return [{"number": 41, "head": "feat/x", "head_sha": "abc123",
                 "title": "[#11] Stats", "body": "Closes #11"}]

    async def get_ci_checks(self, ref):
        return [_check("tests", self.ci_state, "2 failed, 30 passed")]

    async def merge_pr(self, number, merge_method="squash"):
        self.merged.append(number)

    async def delete_branch(self, branch):
        pass

    async def get_issue_comments(self, number):
        return []

    async def add_comment(self, number, body):
        self.comments.append((number, body))

    async def add_labels(self, number, labels):
        self.labels.append((number, labels))

    async def remove_label(self, number, label):
        pass


def _state(github) -> dict:
    return {"github": github, "github_repo": "jrechet/concert-tour-app",
            "reviews": [{"pr_number": 41, "decision": "APPROVE"}]}


async def test_an_approved_pr_on_green_ci_merges():
    from theswarm.agents.techlead import merge_approved_prs

    github = _Repo("success")

    out = await merge_approved_prs(_state(github))

    assert github.merged == [41] and out["merged_prs"] == [41]


async def test_an_approved_pr_on_red_ci_goes_back_to_the_dev():
    from theswarm.agents.techlead import CHANGES_MARKER, merge_approved_prs

    github = _Repo("failure")

    out = await merge_approved_prs(_state(github))

    assert github.merged == [] and out["merged_prs"] == []
    assert out["ci_red_prs"] == [41]
    ((issue, note),) = github.comments
    assert issue == 11
    assert CHANGES_MARKER in note and ci_gate.CI_RED_MARKER in note
    assert "tests" in note and "2 failed, 30 passed" in note
    assert (11, ["status:ready"]) in github.labels


async def test_an_approved_pr_whose_ci_never_finishes_is_left_open():
    from theswarm.agents.techlead import merge_approved_prs

    github = _Repo("in_progress")

    with patch.object(ci_gate, "CI_WAIT_SECONDS", 0):
        out = await merge_approved_prs(_state(github))

    assert github.merged == [] and out["ci_pending_prs"] == [41]
    assert github.comments == []


def test_the_state_declares_the_new_keys():
    from theswarm.config import AgentState

    assert {"ci_red_prs", "ci_pending_prs"} <= set(AgentState.__annotations__)


# ── The end-of-cycle merge on SELF_REPO ────────────────────────────────


async def test_a_held_pr_on_red_ci_stays_open():
    from theswarm.cycle import _merge_held_prs

    github = _Repo("failure")

    merged = await _merge_held_prs(github, [41], None)

    assert merged == [] and github.merged == []


async def test_a_held_pr_on_green_ci_merges():
    from theswarm.cycle import _merge_held_prs

    github = _Repo("success")

    assert await _merge_held_prs(github, [41], None) == [41]


# ── The client ─────────────────────────────────────────────────────────


async def test_the_client_flattens_statuses_and_check_runs():
    from theswarm.infrastructure.resilience import CircuitBreaker
    from theswarm.tools.github import GitHubClient

    commit = MagicMock()
    commit.get_combined_status.return_value = SimpleNamespace(statuses=[
        SimpleNamespace(context="theswarm/review", state="success", description="APPROVE"),
        SimpleNamespace(context="ci/legacy", state="pending", description=None),
    ])
    commit.get_check_runs.return_value = [
        SimpleNamespace(name="tests", status="completed", conclusion="failure",
                        output=SimpleNamespace(title="2 failed")),
        SimpleNamespace(name="e2e", status="in_progress", conclusion=None, output=None),
    ]
    with patch.object(GitHubClient, "__post_init__"):
        client = GitHubClient.__new__(GitHubClient)
        client.repo_name = "owner/repo"
        client._repo = MagicMock()
        client._repo.get_commit.return_value = commit
        client._gh = MagicMock()
        client._breaker = CircuitBreaker(name="test", failure_threshold=999)

    checks = await client.get_ci_checks("abc123")

    assert checks == [
        {"name": "theswarm/review", "state": "success", "summary": "APPROVE"},
        {"name": "ci/legacy", "state": "pending", "summary": ""},
        {"name": "tests", "state": "failure", "summary": "2 failed"},
        {"name": "e2e", "state": "in_progress", "summary": ""},
    ]
    client._repo.get_commit.assert_called_once_with("abc123")


def test_a_merge_pass_shares_one_wait():
    clock = _Clock()
    wait = ci_gate.SharedWait(clock=clock)

    clock.now += ci_gate.CI_WAIT_SECONDS - 40

    assert wait.left() == 40
    clock.now += 100
    assert wait.left() == 0


# ── The harness's CI field ─────────────────────────────────────────────


def _harness():
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("cycle_e2e_ci", root / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_harness_does_not_read_the_swarm_s_own_verdict_as_ci():
    harness = _harness()
    changes_requested = "theswarm/review\tfail\t0\t\tChanges requested: the diff only touches .gitignore\n"
    approved = "theswarm/review\tpass\t0\t\tAPPROVE\n"

    assert harness.ci_verdict(changes_requested) == "none"
    assert harness.ci_verdict(approved) == "none"


def test_the_harness_still_reads_real_ci():
    harness = _harness()
    output = ("theswarm/review\tpass\t0\t\tAPPROVE\n"
              "tests\tfail\t2m1s\thttps://github.com/o/r/actions/runs/1\t\n")

    assert harness.ci_verdict(output) == "RED"
    assert harness.ci_verdict("tests\tpass\t2m1s\thttps://x\t\n") == "green"
