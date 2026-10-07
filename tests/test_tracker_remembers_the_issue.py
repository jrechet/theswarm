"""The cycle tracker remembers the targeted issue (from V1's issue-panel
tests, M6): the theater's pinned issue and a member's four steps read it."""

from __future__ import annotations

import pytest

from theswarm.api import CycleRequest, get_cycle_tracker


@pytest.fixture()
def tracker():
    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    tracker._cycles.clear()
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


def test_tracker_remembers_the_targeted_issue(tracker):
    pinned = tracker.create(CycleRequest(repo="o/r", description="Play on #200", issue_number=200))
    untargeted = tracker.create(CycleRequest(repo="o/r", description="the daily cycle"))
    assert pinned.issue_number == 200
    assert untargeted.issue_number is None
    assert tracker.get(pinned.id).issue_number == 200
