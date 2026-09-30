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
