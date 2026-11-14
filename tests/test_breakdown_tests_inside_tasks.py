"""Every task ships its own tests, written first; no tests-only task after the code.

The breakdown asked for "a test-writing task if the story requires new
tests" while the Dev "always writes tests for new code". Every story on
concert-tour-app since 2026-09-26 ended its chain on such a task, after
the code it tests: seven of eighteen found their tests already on main
(#383, #438, #454, #468, #484, #497, #512) — an iteration, a closing
comment and a story "already on main" in the player, for nothing — and the
others re-tested what their siblings had tested. Test-after, where the
owner's rule is tests first, in the task that writes the code.
"""

from __future__ import annotations

from theswarm.agents.techlead import BREAKDOWN_PROMPT


def test_the_breakdown_asks_for_no_tests_only_task():
    assert "Include a test-writing task" not in BREAKDOWN_PROMPT
    assert "a test task depends on the code it tests" not in BREAKDOWN_PROMPT
    assert "No task only writes tests" in BREAKDOWN_PROMPT


def test_each_task_names_the_tests_it_ships():
    assert "its own tests" in BREAKDOWN_PROMPT
    # The examples show where: in the acceptance criteria.
    assert BREAKDOWN_PROMPT.count("- [ ] Tests:") == 2


def test_the_prompt_still_formats():
    prompt = BREAKDOWN_PROMPT.format(context="ctx", issue_number=1, issue_title="t", issue_body="b")

    assert "Tests:" in prompt and "{" in prompt  # the JSON example keeps its braces


# ── Every sub-task is a Dev's: nobody else picks one ──────────────────
#
# swarm-todo-app#28 (2026-11-11, cycle 8405aa9eef3c): the breakdown made a
# "Cover the delete flow with E2E tests and demo screenshots" task labelled
# `role:qa`. QA is a phase of the cycle, not a picker: nothing ever takes a
# task, and the story stayed open with its feature built.


def test_the_breakdown_asks_for_no_qa_task():
    assert "No QA, E2E or demo task" in BREAKDOWN_PROMPT


def test_a_sub_task_always_carries_the_dev_s_labels_and_no_other_role():
    from theswarm.agents.techlead import task_labels

    assert task_labels(["role:qa", "status:ready"]) == ["role:dev", "status:ready"]
    assert task_labels(["status:backlog", "role:techlead", "area:api"]) == ["role:dev", "status:ready", "area:api"]
    assert task_labels(None) == ["role:dev", "status:ready"]
    assert task_labels(["role:dev", "status:ready", "role:dev"]) == ["role:dev", "status:ready"]


def test_a_task_never_asks_to_close_the_story():
    """swarm-todo-app#31 (2026-11-14): "PR references `Closes #31`" in every
    sub-task's criteria; the story closed with its endpoint unbuilt."""
    assert "never closes the story" in BREAKDOWN_PROMPT
