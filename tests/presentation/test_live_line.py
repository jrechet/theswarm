"""Where a live cycle is, in one line a card can carry.

The owner, 2026-11-11: "je n'arrive pas à savoir où ça en est, si c'est
bloqué, si ça travaille" — three cycles ran on prod and the home said
"issue #841 · running since 08:43 UTC" for each. The theater draws a whole
stage for one cycle; the home and a project's banner list several. The
line reads what the process already holds: the phases a cycle announced
and each agent's last telling words.
"""

from __future__ import annotations

from types import SimpleNamespace

from theswarm.presentation.web import live_line as ll

T0 = 1_000_000.0


def _record(status: str = "running", cycle_id: str = "abc123abc123"):
    return SimpleNamespace(id=cycle_id, status=SimpleNamespace(value=status), repo="o/app", issue_number=12)


PHASES = [{"phase": "po_morning", "ts": T0}, {"phase": "techlead_breakdown", "ts": T0 + 20}, {"phase": "dev_iter", "ts": T0 + 60}]


class TestTheLine:
    def test_the_step_who_works_and_their_last_words(self):
        progress = [{"role": "Dev", "message": "Edit src/routers/venues.py", "ts": T0 + 170},
                    {"role": "TechLead", "message": "3 tasks created", "ts": T0 + 55}]
        line = ll.live_line(_record(), phases=PHASES, progress=progress, now=T0 + 182)
        assert line["step"] == "Dev · 1" and line["agent"] == "Developer"
        assert line["says"] == "Edit src/routers/venues.py" and line["ago"] == "12 s" and not line["quiet"]
        assert [(s["label"], s["state"]) for s in line["steps"]] == [
            ("Plan", "done"), ("Breakdown", "done"), ("Dev · 1", "live"), ("Review", "todo"), ("QA", "todo"), ("Report", "todo")]

    def test_the_words_are_the_working_agent_s_not_the_last_to_speak(self):
        # the review runs; the Dev's last line is older and is not what the card says
        phases = [*PHASES, {"phase": "techlead_review", "ts": T0 + 600}]
        progress = [{"role": "Dev", "message": "Pushed feat/issue-13", "ts": T0 + 590}]
        line = ll.live_line(_record(), phases=phases, progress=progress, now=T0 + 640)
        assert line["step"] == "Review" and line["agent"] == "Tech Lead" and line["says"] == "" and line["ago"] == "40 s"

    def test_nothing_told_for_five_minutes_is_said(self):
        progress = [{"role": "Dev", "message": "Running the tests of the diff", "ts": T0 + 100}]
        line = ll.live_line(_record(), phases=PHASES, progress=progress, now=T0 + 100 + ll.QUIET_AFTER_SECONDS)
        assert line["quiet"] and not line["stalled"] and line["ago"] == "5 min"
        assert ll.live_line(_record(), phases=PHASES, progress=progress, now=T0 + 100 + ll.STALLED_AFTER_SECONDS)["stalled"]
        assert ll.live_line(_record(), phases=PHASES, progress=progress, now=T0 + 100 + 4000)["ago"] == "1 h 06"

    def test_a_cycle_that_announced_nothing_yet(self):
        line = ll.live_line(_record(), phases=[], progress=[], now=T0)
        assert line["step"] == "" and line["agent"] == "" and line["steps"] == [] and not line["quiet"]

    def test_a_queued_cycle_has_no_line(self):
        line = ll.live_line(_record("queued"), phases=PHASES, progress=[], now=T0 + 9000)
        assert line["status"] == "queued" and line["step"] == "" and not line["quiet"] and line["steps"] == []

    def test_long_words_are_cut_and_a_broken_reader_never_raises(self):
        progress = [{"role": "Dev", "message": "x" * 400, "ts": T0 + 70}]
        assert len(ll.live_line(_record(), phases=PHASES, progress=progress, now=T0 + 71)["says"]) == ll.SAYS_MAX
        assert ll.live_line(_record(), phases=[{"nope": 1}], progress=[{"role": None}], now=T0)["status"] == "running"

    def test_it_reads_the_process_s_own_history_by_default(self):
        from theswarm.application.services import progress_bridge as bridge

        bridge.record_phase("live0line0cyc", "qa")
        bridge.record_live_progress("live0line0cyc", "QA", "Recording the demo video")
        line = ll.live_line(_record(cycle_id="live0line0cyc"))
        assert line["step"] == "QA" and line["agent"] == "QA" and line["says"] == "Recording the demo video"
