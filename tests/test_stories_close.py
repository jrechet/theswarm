"""A story closes when its last sub-task is done; a parent is matched exactly.

A merged PR closes its task ("Closes #N"), and nothing ever closed the story
above it: on concert-tour-app on 2026-09-25, #344 (csv-export, all three
PRs merged) and a dozen older stories sat open "in-progress" forever, so the
backlog could not tell built work from work in flight.

And every reader of "Parent: #N" matched it as a substring: "Parent: #32"
is inside "Parent: #321". On TheSwarm, whose issues run #1-#230, a Play on
#22 took the children of #220-#229 for its own.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.tools.github import is_child_of, parent_of


# ── The marker ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("body, parent, expected", [
    ("Do it.\n\nParent: #321", 321, True),
    ("Do it.\n\nParent: #321", 32, False),
    ("Do it.\n\nParent: #32\n", 32, True),
    ("Depends on: #32\n\nParent: #321", 32, False),
    ("", 32, False),
    (None, 32, False),
])
def test_a_parent_is_matched_exactly(body, parent, expected):
    assert is_child_of(body, parent) is expected


def test_the_parent_is_read_off_the_body():
    assert parent_of("Depends on: #322\n\nParent: #321") == 321
    assert parent_of("no parent here") is None
    assert parent_of(None) is None


async def test_the_targeted_picker_does_not_take_a_longer_number_s_children():
    from theswarm.agents import dev

    story = {"number": 32, "title": "Story", "body": "", "labels": [{"name": "status:ready"}], "state": "open"}
    github = AsyncMock()
    github.get_issue = AsyncMock(return_value=story)
    github.get_issues = AsyncMock(return_value=[
        {"number": 330, "title": "Someone else's", "body": "Parent: #321",
         "labels": [{"name": "role:dev"}, {"name": "status:ready"}], "state": "open"},
    ])
    github.get_issue_comments = AsyncMock(return_value=[])

    assert await dev._pick_targeted(github, 32) is None


# ── Closing the story ──────────────────────────────────────────────────


class _GitHub:
    def __init__(self, issues: dict[int, dict]):
        self.issues = issues
        self.closed: list[tuple[int, str]] = []
        self.removed: list[tuple[int, str]] = []

    async def get_issue(self, number):
        return self.issues.get(number)

    async def get_issues(self, labels=None, state="open"):
        return [i for i in self.issues.values() if state == "all" or i["state"] == state]

    async def close_issue(self, number, comment=None):
        self.closed.append((number, comment or ""))
        self.issues[number]["state"] = "closed"

    async def remove_label(self, number, label):
        self.removed.append((number, label))


def _issue(number, body="", state="open", labels=("role:dev",)):
    return {"number": number, "title": f"#{number}", "body": body, "state": state,
            "labels": [{"name": n} for n in labels]}


def _csv_export(**states):
    return _GitHub({
        344: _issue(344, "Export the concerts as CSV", labels=("status:in-progress",)),
        345: _issue(345, "Parent: #344", state=states.get("s345", "closed")),
        346: _issue(346, "Parent: #344", state=states.get("s346", "closed")),
        347: _issue(347, "Depends on: #345\n\nParent: #344", state=states.get("s347", "open")),
    })


async def test_the_last_sub_task_done_closes_the_story():
    from theswarm.agents.techlead import close_finished_stories

    github = _csv_export()

    # #347's PR just merged: GitHub closes the task a moment later.
    closed = await close_finished_stories(github, [347])

    assert closed == [344]
    ((number, comment),) = github.closed
    assert number == 344 and "#345" in comment and "#346" in comment and "#347" in comment
    assert (344, "status:in-progress") in github.removed


async def test_a_story_with_a_sub_task_still_open_stays_open():
    from theswarm.agents.techlead import close_finished_stories

    github = _csv_export(s346="open")

    assert await close_finished_stories(github, [347]) == []
    assert github.closed == []


async def test_a_task_without_a_parent_closes_nothing():
    from theswarm.agents.techlead import close_finished_stories

    github = _GitHub({7: _issue(7, "No parent")})

    assert await close_finished_stories(github, [7]) == []


async def test_a_story_already_closed_is_left_alone():
    from theswarm.agents.techlead import close_finished_stories

    github = _csv_export()
    github.issues[344]["state"] = "closed"

    assert await close_finished_stories(github, [347]) == []
    assert github.closed == []


async def test_closing_never_fails_the_merge():
    from theswarm.agents.techlead import close_finished_stories

    class Broken(_GitHub):
        async def get_issues(self, labels=None, state="open"):
            raise RuntimeError("502")

    assert await close_finished_stories(Broken(_csv_export().issues), [347]) == []


async def test_the_techlead_closes_the_story_after_its_merges():
    from theswarm.agents.techlead import merge_approved_prs

    github = _csv_export()
    github.get_open_prs = AsyncMock(return_value=[
        {"number": 350, "head": "feat/issue-347", "head_sha": "", "title": "[#347] Tests", "body": "Closes #347"},
    ])
    github.merge_pr = AsyncMock()
    github.delete_branch = AsyncMock()

    out = await merge_approved_prs({
        "github": github, "github_repo": "jrechet/concert-tour-app",
        "reviews": [{"pr_number": 350, "decision": "APPROVE"}],
    })

    assert out["merged_prs"] == [350]
    assert out["closed_stories"] == [344]


async def test_the_end_of_cycle_merge_closes_the_story_too():
    from theswarm.cycle import _merge_held_prs

    github = _csv_export()
    github.get_open_prs = AsyncMock(return_value=[
        {"number": 350, "head": "feat/issue-347", "head_sha": "", "title": "[#347] Tests", "body": "Closes #347"},
    ])
    github.merge_pr = AsyncMock()
    github.delete_branch = AsyncMock()

    assert await _merge_held_prs(github, [350], None) == [350]
    assert [n for n, _ in github.closed] == [344]


def test_the_state_declares_closed_stories():
    from theswarm.config import AgentState

    assert "closed_stories" in AgentState.__annotations__


# ── The sweep ──────────────────────────────────────────────────────────


def _sweep():
    import importlib.util
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("sweep_stories", root / "scripts/sweep_finished_stories.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backlog():
    github = _csv_export(s347="closed")
    github.issues[337] = _issue(337, "Filter by venue", labels=("status:in-progress",))
    github.issues[341] = _issue(341, "Parent: #337", state="open")
    return github


async def test_every_finished_story_is_found_without_a_merge():
    from theswarm.agents.techlead import finished_stories

    assert await finished_stories(_backlog()) == [(344, [345, 346, 347])]


async def test_the_sweep_lists_without_closing_by_default(capsys):
    github = _backlog()

    listed = await _sweep().sweep("o/r", apply=False, client=github)

    assert listed == [344] and github.closed == []
    assert "#344" in capsys.readouterr().out


async def test_the_sweep_closes_with_apply():
    github = _backlog()

    closed = await _sweep().sweep("o/r", apply=True, client=github)

    assert closed == [344] and [n for n, _ in github.closed] == [344]


# ── Sub-tasks already on main ──────────────────────────────────────────


async def test_the_dev_loop_closes_a_story_whose_tasks_were_already_built(monkeypatch):
    """csv-export's #354: the Dev closed #355-#357 as already satisfied,
    nothing merged, and the story stayed open."""
    from types import SimpleNamespace

    from theswarm import cycle, cycle_graph

    github = _csv_export(s345="closed", s346="closed", s347="closed")
    progress: list[str] = []

    async def say(role, message):
        progress.append(message)

    async def nothing_to_requeue(config):
        return []

    async def checkpoint(*_a, **_kw):
        return None

    monkeypatch.setattr(cycle, "_requeue_unfinished", nothing_to_requeue)
    rt = SimpleNamespace(
        config=SimpleNamespace(workspace_dir=""), dev_claims_open=True,
        base_state={"github": github}, progress=say, phase_checkpoint=checkpoint,
    )

    await cycle_graph.dev_loop_end({"already_satisfied": [345, 346, 347]}, SimpleNamespace(context=rt))

    assert [n for n, _ in github.closed] == [344]
    assert any("Story #344 done" in m for m in progress)


async def test_the_dev_loop_leaves_stories_alone_when_nothing_was_already_built(monkeypatch):
    from types import SimpleNamespace

    from theswarm import cycle, cycle_graph

    github = _csv_export()

    async def nothing(*_a, **_kw):
        return []

    monkeypatch.setattr(cycle, "_requeue_unfinished", nothing)
    rt = SimpleNamespace(config=SimpleNamespace(workspace_dir=""), dev_claims_open=True,
                         base_state={"github": github}, progress=nothing, phase_checkpoint=nothing)

    await cycle_graph.dev_loop_end({}, SimpleNamespace(context=rt))

    assert github.closed == []
