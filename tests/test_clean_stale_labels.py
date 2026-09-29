"""The stale labels are put back in line with what happened (owner, 2026-09-29)."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_SPEC = importlib.util.spec_from_file_location(
    "clean_stale_labels", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "clean_stale_labels.py")
cleaner = importlib.util.module_from_spec(_SPEC)
sys.modules["clean_stale_labels"] = cleaner  # its dataclasses look themselves up there
_SPEC.loader.exec_module(cleaner)


def _issue(number, labels, title="t", body=""):
    return {"number": number, "title": title, "labels": [{"name": label} for label in labels], "body": body}


OPEN = [
    _issue(199, ["status:in-progress", "role:dev"], "Remaining ticket calculation"),  # merged long ago
    _issue(306, ["status:review", "role:dev"], "City filter tests"),                  # its PR is open
    _issue(218, ["status:in-progress"], "Almost-sold-out badge"),                     # nothing ever came
    _issue(215, ["status:in-progress"], "Warn a fan when almost sold out"),           # story, kids closed
    _issue(205, ["status:ready", "status:in-progress"], "City filter story"),        # double label
    _issue(50, ["status:ready"], "Fine as it is"),
]
CLOSED = [_issue(216, [], body="Parent: #215"), _issue(217, [], body="Parent: #215")]
OPEN_PRS = [{"number": 307, "title": "[#306] City filter tests", "body": "Closes #306"}]
MERGED_PRS = [{"number": 201, "title": "[#199] Remaining tickets", "body": "Closes #199"}]


def _plan():
    return {a.issue: a for a in cleaner.plan(OPEN, CLOSED, OPEN_PRS, MERGED_PRS)}


def test_a_merged_task_is_closed_with_its_pr_named():
    action = _plan()[199]
    assert action.kind == "close" and action.why == "merged in #201"


def test_a_task_with_an_open_pr_is_in_review():
    action = _plan()[306]
    assert action.kind == "review" and action.add == ("status:review",)
    assert action.remove == ()


def test_a_task_nothing_came_of_goes_back_to_ready():
    action = _plan()[218]
    assert action.kind == "ready"
    assert action.remove == ("status:in-progress",) and action.add == ("status:ready",)


def test_a_story_whose_sub_tasks_are_all_closed_is_closed():
    action = _plan()[215]
    assert action.kind == "close" and "#216, #217" in action.why


def test_a_double_label_keeps_ready_only():
    action = _plan()[205]
    assert action.kind == "ready" and action.remove == ("status:in-progress",)


def test_an_issue_with_a_true_label_is_left_alone():
    assert 50 not in _plan()


def test_every_change_says_why_on_the_issue():
    text = cleaner.comment(_plan()[218], ("status:in-progress",))
    assert "Back to `status:ready`" in text and "`status:in-progress`" in text
    assert cleaner.MARKER in text


def test_an_old_stale_task_is_closed_as_not_planned():
    old = dict(_issue(1, ["status:in-progress", "role:dev"], "Set up FastAPI project structure"),
               created_at="2026-04-16T09:00:00Z")
    recent = dict(_issue(218, ["status:in-progress"], "Almost-sold-out badge"), created_at="2026-09-13T09:00:00Z")

    actions = {a.issue: a for a in cleaner.plan([old, recent], [], [], [], close_before="2026-09-01")}

    assert actions[1].kind == "not_planned" and "2026-04-16" in actions[1].why
    assert actions[218].kind == "ready"
    assert "reopen it to ask again" in cleaner.comment(actions[1], ("status:in-progress",))
