"""A sub-task the Dev started but never finished must not be abandoned.

Prod cycle d4aad3415e99 was asked for a city filter. The TechLead split it
into three (#206 endpoint, #207 dropdown, #208 tests). The Dev delivered
#206, and ended on "No more ready tasks" with #207 and #208 sitting in
`status:in-progress` — started, never finished, never requeued. The picker
only ever asked for `status:ready`, so they were invisible: to the rest of
that loop, and to every later cycle. The cycle then reported itself
completed having delivered one third of the feature.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.agents.dev import _pick_targeted


def _issue(number, labels, body="Parent: #205", state="open"):
    return {
        "number": number, "title": f"task {number}", "state": state,
        "labels": [{"name": n} for n in labels], "body": body,
    }


def _github(target, children):
    gh = AsyncMock()
    gh.get_issue = AsyncMock(return_value=target)
    gh.get_issues = AsyncMock(return_value=children)
    return gh


PARENT = _issue(205, ["status:in-progress"], body="the feature")


# ── The exact production failure ───────────────────────────────────────


async def test_a_started_but_unfinished_child_is_picked_up_again():
    gh = _github(PARENT, [
        _issue(206, ["role:dev", "status:review"]),   # done
        _issue(207, ["role:dev", "status:in-progress"]),  # stranded
        _issue(208, ["role:dev", "status:in-progress"]),  # stranded
    ])

    task = await _pick_targeted(gh, 205)

    assert task is not None, "the loop would end on 'no more ready tasks'"
    assert task["number"] in (207, 208)


async def test_a_fresh_task_is_preferred_over_resuming_a_half_done_one():
    gh = _github(PARENT, [
        _issue(207, ["role:dev", "status:in-progress"]),
        _issue(208, ["role:dev", "status:ready"]),
    ])

    assert (await _pick_targeted(gh, 205))["number"] == 208


# ── What must still be refused ─────────────────────────────────────────


async def test_work_already_in_review_is_not_re_picked():
    gh = _github(PARENT, [_issue(206, ["role:dev", "status:review"])])
    assert await _pick_targeted(gh, 205) is None


async def test_another_features_children_are_never_stolen():
    """A targeted cycle implements its own issue or nothing."""
    gh = _github(PARENT, [
        _issue(300, ["role:dev", "status:ready"], body="Parent: #299"),
    ])
    assert await _pick_targeted(gh, 205) is None


async def test_a_closed_child_is_not_picked():
    gh = _github(PARENT, [
        _issue(207, ["role:dev", "status:ready"], state="closed"),
    ])
    assert await _pick_targeted(gh, 205) is None


async def test_a_child_without_the_dev_role_is_not_picked():
    gh = _github(PARENT, [_issue(207, ["role:qa", "status:ready"])])
    assert await _pick_targeted(gh, 205) is None


# ── The target itself keeps priority ───────────────────────────────────


async def test_a_directly_implementable_target_wins_over_its_children():
    gh = _github(
        _issue(205, ["role:dev", "status:ready"], body="the feature"),
        [_issue(207, ["role:dev", "status:ready"])],
    )
    assert (await _pick_targeted(gh, 205))["number"] == 205


async def test_a_closed_target_yields_nothing():
    gh = _github(_issue(205, ["role:dev"], state="closed"), [])
    assert await _pick_targeted(gh, 205) is None
