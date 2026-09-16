"""A sub-task that failed must not starve the ones nobody has tried.

GitHub returns children newest first, and the picker took them in that
order. The end-to-end test task — written last by the TechLead, so listed
first — was re-picked every iteration. Cycle c865170a1c4d spent all five
iterations failing #89 and delivered none of #86, #87, #88, which were
ready, smaller, and untouched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.agents.dev import _pick_targeted, pick_task


def _child(number: int, *, parent: int = 85, status: str = "status:ready") -> dict:
    return {
        "number": number,
        "title": f"Task {number}",
        "body": f"Do the thing.\n\nParent: #{parent}",
        "state": "open",
        "labels": [{"name": "role:dev"}, {"name": status}],
    }


def _github(target: dict, children: list[dict], failures: dict[int, int] | None = None) -> AsyncMock:
    gh = AsyncMock()
    gh.get_issue = AsyncMock(return_value=target)
    gh.get_issues = AsyncMock(return_value=children)
    marker = "<!-- swarm:attempt failed -->\n⏱ Attempt failed — CLI timed out after 546s"

    async def comments(number: int) -> list[dict]:
        return [{"body": marker}] * (failures or {}).get(number, 0)

    gh.get_issue_comments = AsyncMock(side_effect=comments)
    return gh


def _story(number: int = 85) -> dict:
    return {
        "number": number, "title": "Story", "body": "", "state": "open",
        "labels": [{"name": "status:backlog"}],
    }


# GitHub's own order: newest first.
NEWEST_FIRST = [_child(89), _child(88), _child(87), _child(86)]


class TestRotation:
    async def test_with_no_history_the_first_candidate_wins(self):
        gh = _github(_story(), list(NEWEST_FIRST))

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 89

    async def test_a_tried_task_goes_behind_the_untried_ones(self):
        gh = _github(_story(), list(NEWEST_FIRST))

        picked = await _pick_targeted(gh, 85, [89])

        assert picked["number"] == 88

    async def test_each_failure_advances_to_the_next_task(self):
        gh = _github(_story(), list(NEWEST_FIRST))
        attempted: list[int] = []

        picked_order = []
        for _ in range(4):
            task = await _pick_targeted(gh, 85, attempted)
            picked_order.append(task["number"])
            attempted.append(task["number"])

        assert picked_order == [89, 88, 87, 86]

    async def test_once_all_have_been_tried_the_least_tried_comes_back(self):
        """Not a dead end: with nothing fresh left, retrying is right."""
        gh = _github(_story(), list(NEWEST_FIRST))

        picked = await _pick_targeted(gh, 85, [89, 89, 88, 87, 86])

        assert picked["number"] == 88

    async def test_the_worst_offender_is_offered_last(self):
        gh = _github(_story(), list(NEWEST_FIRST))

        picked = await _pick_targeted(gh, 85, [89, 89, 89])

        assert picked["number"] != 89

    async def test_history_of_unrelated_tasks_changes_nothing(self):
        gh = _github(_story(), list(NEWEST_FIRST))

        picked = await _pick_targeted(gh, 85, [1234, 5678])

        assert picked["number"] == 89


class TestRotationRespectsExistingRules:
    async def test_with_equal_attempts_ready_beats_in_progress(self):
        """A clean start still beats resuming someone else's half-done work
        — as long as neither has been tried here."""
        children = [
            _child(89, status="status:in-progress"),
            _child(88, status="status:ready"),
        ]
        gh = _github(_story(), children)

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 88

    async def test_an_untried_in_progress_sibling_beats_a_failed_ready_task(self):
        """The trap: a task that fails is requeued to `ready`; its siblings,
        left in-progress by a cancelled cycle, sat one tier down. "Ready
        first" then re-picked the failed task every iteration (cycle
        0793e29ce7c7 on #89, with #86, #87, #88 untried)."""
        children = [
            _child(89, status="status:ready"),          # just failed, requeued
            _child(88, status="status:in-progress"),
            _child(87, status="status:in-progress"),
        ]
        gh = _github(_story(), children)

        picked = await _pick_targeted(gh, 85, [89])

        assert picked["number"] == 88

    async def test_the_production_trap_over_five_iterations(self):
        """Every sibling in-progress, the failing one bouncing back to ready
        after each attempt: the other three must still all get their turn."""
        gh = _github(_story(), [
            _child(89, status="status:ready"),
            _child(88, status="status:in-progress"),
            _child(87, status="status:in-progress"),
            _child(86, status="status:in-progress"),
        ])
        attempted: list[int] = []
        order = []
        for _ in range(5):
            task = await _pick_targeted(gh, 85, attempted)
            attempted.append(task["number"])
            order.append(task["number"])

        assert order[:4] == [89, 88, 87, 86]

    async def test_a_child_in_review_is_never_picked(self):
        children = [_child(89, status="status:review"), _child(88)]
        gh = _github(_story(), children)

        picked = await _pick_targeted(gh, 85, [88, 88])

        assert picked["number"] == 88

    async def test_children_of_another_parent_are_ignored(self):
        children = [_child(89, parent=79), _child(88)]
        gh = _github(_story(), children)

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 88

    async def test_no_workable_child_returns_none(self):
        gh = _github(_story(), [_child(89, status="status:review")])

        assert await _pick_targeted(gh, 85, []) is None

    async def test_a_directly_implementable_target_is_unaffected(self):
        target = {
            "number": 90, "title": "Task", "body": "", "state": "open",
            "labels": [{"name": "role:dev"}, {"name": "status:ready"}],
        }
        gh = _github(target, [])

        picked = await _pick_targeted(gh, 90, [90, 90])

        assert picked["number"] == 90


class TestPickTaskRecordsTheAttempt:
    async def test_the_attempt_is_recorded_before_the_work_starts(self):
        """An iteration that dies mid-implementation is exactly the one that
        must not be offered again ahead of everything else."""
        gh = _github(_story(), list(NEWEST_FIRST))
        attempted: list[int] = []

        await pick_task({
            "github": gh, "target_issue": 85, "attempted_tasks": attempted,
        })

        assert attempted == [89]

    async def test_consecutive_picks_accumulate(self):
        gh = _github(_story(), list(NEWEST_FIRST))
        attempted: list[int] = []
        state = {"github": gh, "target_issue": 85, "attempted_tasks": attempted}

        await pick_task(state)
        await pick_task(state)

        assert attempted == [89, 88]

    async def test_a_missing_list_does_not_raise(self):
        """Callers outside the dev loop (the CLI, tests) pass no history."""
        gh = _github(_story(), list(NEWEST_FIRST))

        result = await pick_task({"github": gh, "target_issue": 85})

        assert result["task"]["number"] == 89

    async def test_nothing_is_recorded_when_no_task_is_available(self):
        gh = _github(_story(), [])
        attempted: list[int] = []

        await pick_task({
            "github": gh, "target_issue": 85, "attempted_tasks": attempted,
        })

        assert attempted == []


class TestTheProductionScenario:
    async def test_four_subtasks_one_of_which_always_fails(self):
        """#89 failed every time it was tried. The other three must still
        get their turn — the difference between delivering nothing and
        delivering three quarters of the feature."""
        gh = _github(_story(), list(NEWEST_FIRST))
        attempted: list[int] = []
        delivered = []

        for _ in range(5):  # MAX_DEV_ITERATIONS
            task = await _pick_targeted(gh, 85, attempted)
            attempted.append(task["number"])
            if task["number"] != 89:  # 89 is the one that cannot finish
                delivered.append(task["number"])

        assert sorted(set(delivered)) == [86, 87, 88]

    @pytest.mark.parametrize("iterations", [2, 3, 4, 5])
    def test_no_task_is_tried_twice_before_another_is_tried_once(
        self, iterations,
    ):
        """The invariant, stated directly: attempt counts stay within one of
        each other while untried work remains."""
        tried: list[int] = []
        pool = [89, 88, 87, 86]

        for _ in range(iterations):
            nxt = min(pool, key=lambda n: (tried.count(n), pool.index(n)))
            tried.append(nxt)

        counts = [tried.count(n) for n in pool]
        assert max(counts) - min(counts) <= 1


class TestEarlierCyclesCount:
    """What earlier cycles left on the issue orders the very first pick.

    Every self-cycle started with #89 — the heavy end-to-end task that had
    timed out in the cycle before, and the one before that — and lost the
    first sixteen minutes rediscovering it (#99)."""

    async def test_a_task_that_failed_last_cycle_goes_behind_fresh_siblings(self):
        gh = _github(_story(), list(NEWEST_FIRST), failures={89: 2})

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 88

    async def test_this_cycles_attempts_still_come_first(self):
        """A sibling untried today beats one tried today, whatever history says."""
        gh = _github(_story(), list(NEWEST_FIRST), failures={88: 3})

        picked = await _pick_targeted(gh, 85, [89, 87, 86])

        assert picked["number"] == 88

    async def test_fewer_past_failures_first(self):
        gh = _github(_story(), list(NEWEST_FIRST), failures={89: 3, 88: 1, 87: 2})

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 86

    async def test_history_comes_back_last_not_never(self):
        gh = _github(_story(), [_child(89)], failures={89: 4})

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 89

    async def test_a_comments_api_failure_changes_nothing(self):
        gh = _github(_story(), list(NEWEST_FIRST))
        gh.get_issue_comments = AsyncMock(side_effect=RuntimeError("503"))

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 89

    async def test_a_surprising_payload_changes_nothing(self):
        gh = _github(_story(), list(NEWEST_FIRST))
        gh.get_issue_comments = AsyncMock(return_value=None)

        picked = await _pick_targeted(gh, 85, [])

        assert picked["number"] == 89
