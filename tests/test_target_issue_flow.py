"""Issue-driven flow P1 (theswarm#23): a cycle pinned to one GitHub issue.

`POST /api/cycle {"repo": …, "issue_number": N}` must implement issue #N and
nothing else: the TechLead breakdown scopes to it, the dev loop picks it (or
its `Parent: #N` children once broken down), and a targeted cycle never
drains unrelated backlog.
"""

from __future__ import annotations

from unittest.mock import patch

from theswarm.agents.dev import pick_task
from theswarm.agents.techlead import breakdown_stories
from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker, run_api_cycle
from theswarm.config import AgentState, CycleConfig
from theswarm.cycle import _build_base_state


class _FakeGitHub:
    """In-memory issue store mimicking GitHubClient's dict shape."""

    def __init__(self, issues: list[dict]) -> None:
        self.issues = {i["number"]: i for i in issues}
        self.created: list[dict] = []
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

    async def create_issue(self, title, body="", labels=None, assignees=None) -> dict:
        number = max(self.issues, default=0) + 1
        issue = {"number": number, "title": title, "body": body,
                 "labels": list(labels or []), "state": "open"}
        self.issues[number] = issue
        self.created.append(issue)
        return issue

    async def add_labels(self, number: int, labels: list[str]) -> None:
        self.label_ops.append(("add", number, tuple(labels)))
        self.issues[number]["labels"] = list(
            set(self.issues[number]["labels"]) | set(labels)
        )

    async def remove_label(self, number: int, label: str) -> None:
        self.label_ops.append(("remove", number, label))
        if label in self.issues[number]["labels"]:
            self.issues[number]["labels"].remove(label)


def _issue(number, title="t", labels=(), body="", state="open"):
    return {"number": number, "title": title, "labels": list(labels),
            "body": body, "state": state}


# ── Transport: request → config → agent state ─────────────────────────


def test_cycle_request_accepts_issue_number():
    assert CycleRequest(repo="o/r", issue_number=42).issue_number == 42
    assert CycleRequest(repo="o/r").issue_number is None


def test_agent_state_declares_target_issue():
    assert "target_issue" in AgentState.__annotations__


def test_base_state_carries_target_issue():
    config = CycleConfig(github_repo="", target_issue=7)
    assert _build_base_state(config)["target_issue"] == 7


async def test_run_api_cycle_pins_config_to_the_issue():
    captured: dict = {}

    async def fake_cycle(config, **kwargs):
        captured["target"] = config.target_issue
        return {"date": "2026-08-30", "cost_usd": 0.0, "prs": [], "reviews": []}

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="owner/some-repo", issue_number=146))

    with patch("theswarm.cycle.run_daily_cycle", side_effect=fake_cycle):
        await run_api_cycle(
            cycle_id=record.id, repo="owner/some-repo", description="",
            callback_url="", allowed_repos=[], issue_number=146,
        )

    assert captured["target"] == 146
    assert tracker.get(record.id).status == CycleStatus.COMPLETED


# ── Dev: targeted pick ─────────────────────────────────────────────────


async def test_targeted_pick_takes_the_issue_whatever_its_status():
    """Play on a backlog task must not wait for the PO to mark it ready."""
    github = _FakeGitHub([
        _issue(5, "unrelated ready", ["role:dev", "status:ready"]),
        _issue(9, "the target", ["role:dev", "status:backlog"]),
    ])

    result = await pick_task({"github": github, "target_issue": 9})

    assert result["task"]["number"] == 9
    assert "status:in-progress" in github.issues[9]["labels"]


async def test_targeted_pick_prefers_children_once_broken_down():
    github = _FakeGitHub([
        _issue(9, "story", ["status:in-progress"]),  # broken down, no role:dev
        _issue(5, "unrelated ready", ["role:dev", "status:ready"]),
        _issue(12, "child task", ["role:dev", "status:ready"], body="Do it\n\nParent: #9"),
    ])

    result = await pick_task({"github": github, "target_issue": 9})

    assert result["task"]["number"] == 12


async def test_targeted_pick_never_drains_unrelated_backlog():
    """Target done (in review), no children left → None, not issue #5."""
    github = _FakeGitHub([
        _issue(9, "the target", ["role:dev", "status:review"]),
        _issue(5, "unrelated ready", ["role:dev", "status:ready"]),
    ])

    result = await pick_task({"github": github, "target_issue": 9})

    assert result["task"] is None
    assert github.issues[5]["labels"] == ["role:dev", "status:ready"]  # untouched


async def test_targeted_pick_handles_missing_or_closed_issue():
    github = _FakeGitHub([_issue(9, "done", ["role:dev"], state="closed")])

    assert (await pick_task({"github": github, "target_issue": 9}))["task"] is None
    assert (await pick_task({"github": github, "target_issue": 404}))["task"] is None


async def test_untargeted_pick_keeps_backlog_behaviour():
    github = _FakeGitHub([_issue(5, "ready task", ["role:dev", "status:ready"])])

    result = await pick_task({"github": github})

    assert result["task"]["number"] == 5


# ── TechLead: scoped breakdown ─────────────────────────────────────────


class _FakeClaude:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def run(self, prompt, **kwargs):
        self.calls += 1

        class R:
            text = self.text
            total_tokens = 10
            cost_usd = 0.0
        return R()


async def test_breakdown_scopes_to_the_target_story():
    github = _FakeGitHub([
        _issue(9, "target story", ["status:backlog"], body="Build the dashboard"),
        _issue(5, "unrelated ready story", ["status:ready"], body="Other work"),
    ])
    claude = _FakeClaude('[{"title": "T1", "body": "B1"}]')

    await breakdown_stories({"github": github, "claude": claude, "target_issue": 9})

    assert claude.calls == 1  # only the target, not the unrelated ready story
    assert len(github.created) == 1
    assert "Parent: #9" in github.created[0]["body"]
    # Unrelated ready story untouched
    assert github.issues[5]["labels"] == ["status:ready"]


async def test_breakdown_skips_target_that_is_already_a_task():
    github = _FakeGitHub([_issue(9, "small task", ["role:dev", "status:ready"])])
    claude = _FakeClaude("[]")

    result = await breakdown_stories(
        {"github": github, "claude": claude, "target_issue": 9},
    )

    assert claude.calls == 0
    assert "No issues to break down" in result["result"]


async def test_breakdown_reports_missing_target():
    github = _FakeGitHub([])
    claude = _FakeClaude("[]")

    result = await breakdown_stories(
        {"github": github, "claude": claude, "target_issue": 404},
    )

    assert claude.calls == 0
    assert "404" in result["result"]
