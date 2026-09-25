"""A sub-task waits for the sub-tasks it depends on.

The breakdown ordered its tasks "by dependency" in prose only, and the Dev
took any ready one. At width 2 (V2 M5b) the first two start together: in
9d3174f41829 the stats schemas (#322) and the endpoints over them (#323)
were built side by side, each wrote its own version of the other's code,
and #325 conflicted with its sibling and never merged. At width 1 the
test task could still run before the code it tests had merged.

The breakdown now names what each task needs (`depends_on`, earlier
positions only); the TechLead writes it on the issue ("Depends on: #N"),
and a picker leaves a task alone while any of those is still open.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from theswarm.agents import dev
from theswarm.agents.schemas import Breakdown
from theswarm.tools.claude import ClaudeResult


def _claude(structured):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=ClaudeResult(
        text="", backend="sdk", structured=structured, input_tokens=1, output_tokens=1,
        total_tokens=2, cost_usd=0.01,
    ))
    return claude


# ── The breakdown ──────────────────────────────────────────────────────


def test_the_schema_carries_dependencies_and_defaults_to_none():
    parsed = Breakdown.model_validate({"tasks": [
        {"title": "Schemas"}, {"title": "Endpoints", "depends_on": [1]},
    ]})

    assert [t.depends_on for t in parsed.tasks] == [[], [1]]


async def test_the_techlead_writes_what_each_task_waits_for():
    from theswarm.agents.techlead import breakdown_stories

    story = {"number": 321, "title": "Stats", "body": "Cities and venues", "labels": ["status:ready"]}
    github = AsyncMock()
    github.get_issues = AsyncMock(side_effect=[[story], []])
    github.create_issue = AsyncMock(side_effect=[{"number": 322}, {"number": 323}, {"number": 324}])
    claude = _claude({"tasks": [
        {"title": "Add response schemas", "body": "Schemas"},
        {"title": "Implement the endpoints", "body": "Endpoints", "depends_on": [1]},
        {"title": "Write the tests", "body": "Tests", "depends_on": [1, 2]},
    ]})

    await breakdown_stories({"github": github, "claude": claude, "workspace": "/ws", "context": ""})

    bodies = [call.kwargs["body"] for call in github.create_issue.await_args_list]
    assert "Depends on:" not in bodies[0]
    assert "Depends on: #322" in bodies[1]
    assert "Depends on: #322, #323" in bodies[2]
    assert all("Parent: #321" in body for body in bodies)


async def test_a_dependency_on_itself_or_a_later_task_is_dropped():
    from theswarm.agents.techlead import breakdown_stories

    story = {"number": 321, "title": "Stats", "body": "b", "labels": ["status:ready"]}
    github = AsyncMock()
    github.get_issues = AsyncMock(side_effect=[[story], []])
    github.create_issue = AsyncMock(side_effect=[{"number": 322}, {"number": 323}])
    claude = _claude({"tasks": [
        {"title": "A", "body": "a", "depends_on": [1, 2]},
        {"title": "B", "body": "b", "depends_on": [2, 9, 0, 1]},
    ]})

    await breakdown_stories({"github": github, "claude": claude, "workspace": "/ws", "context": ""})

    bodies = [call.kwargs["body"] for call in github.create_issue.await_args_list]
    assert "Depends on:" not in bodies[0]
    assert bodies[1].count("Depends on: #322") == 1 and "#323" not in bodies[1].split("Depends on:")[1]


def test_the_prompt_asks_for_dependencies():
    from theswarm.agents.techlead import BREAKDOWN_PROMPT

    assert "depends_on" in BREAKDOWN_PROMPT


# ── The pickers ────────────────────────────────────────────────────────


def _issue(number: int, *, body: str = "", labels=("role:dev", "status:ready"), state="open") -> dict:
    return {"number": number, "title": f"Task {number}", "body": body,
            "labels": [{"name": n} for n in labels], "state": state}


def test_the_dependencies_are_read_off_the_body():
    assert dev.depends_on({"body": "Do it.\n\nDepends on: #322, #323\n\nParent: #321"}) == [322, 323]
    assert dev.depends_on({"body": "Parent: #321"}) == []
    assert dev.depends_on({"body": None}) == []


class _GitHub:
    def __init__(self, target: dict, children: list[dict]):
        self.target = target
        self.children = children
        self.comments: dict[int, list] = {}

    async def get_issue(self, number):
        return self.target if number == self.target["number"] else None

    async def get_issues(self, labels=None, state="open"):
        return [c for c in self.children if c.get("state") != "closed"]

    async def get_issue_comments(self, number):
        return []


STORY = _issue(321, labels=("status:in-progress",))


async def test_a_task_waits_while_its_dependency_is_open():
    github = _GitHub(STORY, [
        _issue(323, body="Depends on: #322\n\nParent: #321"),
        _issue(322, body="Parent: #321", labels=("role:dev", "status:review")),
    ])

    assert await dev._pick_targeted(github, 321) is None


async def test_a_task_starts_once_its_dependency_is_closed():
    github = _GitHub(STORY, [
        _issue(323, body="Depends on: #322\n\nParent: #321"),
        _issue(322, body="Parent: #321", state="closed"),
    ])

    task = await dev._pick_targeted(github, 321)

    assert task["number"] == 323


async def test_a_sibling_dev_does_not_start_what_depends_on_the_task_it_watched_start():
    """Width 2: the first Dev claimed #322; #323 needs it, so the second
    Dev gets nothing rather than a conflict."""
    github = _GitHub(STORY, [
        _issue(322, body="Parent: #321"),
        _issue(323, body="Depends on: #322\n\nParent: #321"),
    ])

    first = await dev._pick_targeted(github, 321, exclude=[])
    second = await dev._pick_targeted(github, 321, exclude=[first["number"]])

    assert first["number"] == 322
    assert second is None


async def test_independent_siblings_still_run_side_by_side():
    github = _GitHub(STORY, [
        _issue(322, body="Parent: #321"),
        _issue(324, body="Parent: #321"),
    ])

    first = await dev._pick_targeted(github, 321, exclude=[])
    second = await dev._pick_targeted(github, 321, exclude=[first["number"]])

    assert {first["number"], second["number"]} == {322, 324}


async def test_the_backlog_picker_skips_a_waiting_task():
    ready = [_issue(323, body="Depends on: #322"), _issue(330)]
    everything = [*ready, _issue(322, labels=("role:dev", "status:in-progress"))]

    github = MagicMock()

    async def get_issues(labels=None, state="open"):
        return ready if labels and "status:ready" in labels else everything

    github.get_issues = get_issues
    github.add_labels = AsyncMock()
    github.remove_label = AsyncMock()

    out = await dev._pick_and_claim({}, github)

    assert out["task"]["number"] == 330
