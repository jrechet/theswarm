"""The phase channel: cycle.py announces phases, the bridge stops guessing.

The bridge used to publish PhaseChanged whenever a different role spoke,
with the message as the phase name — so "Checking branch protection…" and
"Starting development loop…" were phases, and the real ones (po_morning,
dev_loop…) never appeared anywhere. The theater's graph needs the real
ones, in order.
"""

from __future__ import annotations

import pytest

from theswarm.application.events.bus import EventBus
from theswarm.application.services import progress_bridge as pb
from theswarm.domain.cycles.events import AgentActivity, PhaseChanged
from theswarm.domain.cycles.value_objects import PHASE_ROLE


@pytest.fixture(autouse=True)
def _clean():
    pb._LIVE_PROGRESS.clear()
    pb._PHASE_HISTORY.clear()
    yield
    pb._LIVE_PROGRESS.clear()
    pb._PHASE_HISTORY.clear()


def _bridge():
    bus = EventBus()
    phases: list[PhaseChanged] = []
    activity: list[AgentActivity] = []

    async def on_phase(event):
        phases.append(event)

    async def on_activity(event):
        activity.append(event)

    bus.subscribe(PhaseChanged, on_phase)
    bus.subscribe(AgentActivity, on_activity)
    return pb.ProgressBridge(event_bus=bus, cycle_id="c1", project_id="o/r"), phases, activity


class TestHistory:
    def test_phases_are_kept_in_order(self):
        pb.record_phase("c1", "po_morning")
        pb.record_phase("c1", "techlead_breakdown")
        pb.record_phase("c1", "dev_loop")

        assert [p["phase"] for p in pb.get_phase_history("c1")] == [
            "po_morning", "techlead_breakdown", "dev_loop",
        ]

    def test_repeats_are_kept_too(self):
        """The Dev iterates and the TechLead reviews after each iteration —
        the graph needs every visit, not a set."""
        for phase in ("dev_iter", "techlead_review", "dev_iter", "techlead_review"):
            pb.record_phase("c1", phase)

        assert [p["phase"] for p in pb.get_phase_history("c1")] == [
            "dev_iter", "techlead_review", "dev_iter", "techlead_review",
        ]

    def test_cycles_do_not_leak_into_each_other(self):
        pb.record_phase("c1", "po_morning")
        pb.record_phase("c2", "qa")

        assert [p["phase"] for p in pb.get_phase_history("c1")] == ["po_morning"]

    def test_unknown_cycle_has_no_history(self):
        assert pb.get_phase_history("nope") == []

    def test_the_history_returned_is_a_copy(self):
        pb.record_phase("c1", "po_morning")
        pb.get_phase_history("c1").append({"phase": "tampered"})

        assert len(pb.get_phase_history("c1")) == 1

    def test_old_cycles_are_evicted_not_the_current_one(self, monkeypatch):
        monkeypatch.setattr(pb, "_PHASE_HISTORY_MAX", 2)
        pb.record_phase("old", "po_morning")
        pb.record_phase("mid", "po_morning")
        pb.record_phase("new", "po_morning")
        pb.record_phase("mid", "qa")  # touched again: stays

        assert pb.get_phase_history("old") == []
        assert len(pb.get_phase_history("mid")) == 2
        assert len(pb.get_phase_history("new")) == 1


class TestTheBridgeHearsPhases:
    async def test_a_phase_announcement_becomes_the_real_phase_changed(self):
        bridge, phases, _ = _bridge()

        await bridge(PHASE_ROLE, "techlead_breakdown")

        assert len(phases) == 1
        assert phases[0].phase == "techlead_breakdown"
        assert phases[0].agent == "techlead"
        assert str(phases[0].cycle_id) == "c1"

    async def test_the_owner_is_the_agent_of_record(self):
        bridge, phases, _ = _bridge()

        for phase in ("po_morning", "dev_iter", "techlead_review", "qa", "po_evening"):
            await bridge(PHASE_ROLE, phase)

        assert [p.agent for p in phases] == ["po", "dev", "techlead", "qa", "po"]

    async def test_it_lands_in_the_history(self):
        bridge, _, _ = _bridge()

        await bridge(PHASE_ROLE, "po_morning")
        await bridge(PHASE_ROLE, "techlead_breakdown")

        assert [p["phase"] for p in pb.get_phase_history("c1")] == [
            "po_morning", "techlead_breakdown",
        ]

    async def test_it_is_not_a_live_progress_message(self):
        """A phase is not something an agent said."""
        bridge, _, _ = _bridge()

        await bridge(PHASE_ROLE, "po_morning")

        assert pb.get_live_progress("c1") == []

    async def test_an_unknown_phase_is_still_announced_under_its_own_name(self):
        bridge, phases, _ = _bridge()

        await bridge(PHASE_ROLE, "something_new")

        assert phases[0].phase == "something_new"
        assert phases[0].agent == "something_new"


class TestTheGuessIsRetired:
    async def test_after_a_real_phase_a_role_switch_is_activity_not_a_phase(self):
        bridge, phases, activity = _bridge()
        await bridge(PHASE_ROLE, "dev_loop")

        await bridge("Dev", "Starting development loop…")

        assert [p.phase for p in phases] == ["dev_loop"]
        assert any(a.detail == "Starting development loop…" for a in activity)

    async def test_the_first_sentence_of_an_agent_is_no_longer_swallowed(self):
        """The heuristic returned early on a role switch: an agent's first
        message never reached the activity stream."""
        bridge, _, activity = _bridge()
        await bridge(PHASE_ROLE, "po_morning")

        await bridge("PO", "Shaped #21 into two stories")
        await bridge("TechLead", "Split #21 into 3 tasks")

        assert [a.detail for a in activity] == [
            "Shaped #21 into two stories", "Split #21 into 3 tasks",
        ]

    async def test_before_any_real_phase_the_old_guess_still_works(self):
        """CLI cycles and older callers announce nothing; they keep what
        they had."""
        bridge, phases, _ = _bridge()

        await bridge("PO", "Starting daily planning…")
        await bridge("Dev", "Starting development loop…")

        assert [p.agent for p in phases] == ["PO", "Dev"]

    async def test_pr_events_are_still_detected_after_a_real_phase(self):
        bridge, _, activity = _bridge()
        await bridge(PHASE_ROLE, "dev_iter")

        await bridge("Dev", "PR #235 opened: https://example/pull/235")

        opened = [a for a in activity if a.action == "pr_opened"]
        assert len(opened) == 1
        assert opened[0].metadata["pr_number"] == 235
