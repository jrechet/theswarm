"""The control room knows more of a live cycle (A2).

What a cycle has spent was on its row at the end only: a card said nothing
of money for the half hour it ran. And two Devs side by side shared one
station and one voice — nobody could tell who did which task (defect 9).
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace

from claude_agent_sdk import ResultMessage, SystemMessage

from theswarm import cycle_graph
from theswarm.agents import dev
from theswarm.api import CycleRequest, CycleStatus, CycleTracker
from theswarm.application.services import progress_bridge
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI


# ── The spend so far ───────────────────────────────────────────────────


async def test_every_call_adds_what_it_cost(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def stream(prompt, options):
        yield SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": "s-1"})
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="s-1", total_cost_usd=0.25, usage={}, result="ok")

    monkeypatch.setattr(claude_mod, "_sdk_query", stream)
    tracker = CycleTracker()
    record = tracker.create(CycleRequest(repo="o/r", issue_number=1))
    claude = ClaudeCLI(model="haiku", on_spend=lambda usd: tracker.add_spend(record.id, usd))

    await claude.run("one")
    await claude.with_settings("opus").run("two")  # a persona's Claude counts on the same cycle

    assert record.spent_usd == 0.5
    tracker.add_spend("unknown", 1.0)  # never raises


def test_the_home_card_says_it():
    from theswarm.presentation.web.routes import home

    record = SimpleNamespace(id="abc123def456", repo="o/r", issue_number=7, description="Add a thing",
                             status=CycleStatus.RUNNING, started_at="", created_at="", waiting="", spent_usd=1.237)
    card = _card(home, record)
    assert card["spent"] == "$1.24"
    record.spent_usd = 0.0
    assert _card(home, record)["spent"] == ""


def _card(home, record):
    from unittest.mock import patch

    with patch("theswarm.presentation.web.shell.live_cycles", return_value=[record]):
        return home._now_cards(SimpleNamespace(base_path="/swarm"), {})[0]


# ── Two Devs side by side: who does what ───────────────────────────────


async def test_a_lane_s_lines_carry_its_task_once_it_picked():
    heard: list[str] = []

    async def emit(text):
        heard.append(text)

    base = ClaudeCLI(model="haiku", on_event=emit)
    lane = {"task": None}
    mine = cycle_graph._lane_claude(base, lane)

    await mine.on_event("Reading the backlog")
    dev._name_lane({"lane": lane}, {"number": 901})
    await mine.on_event("Bash: pytest -q")

    assert heard == ["Reading the backlog", "task 901 — Bash: pytest -q"]
    assert dataclasses.is_dataclass(mine) and base.on_event is emit  # the shared one is untouched
    assert cycle_graph._lane_claude(None, lane) is None
    dev._name_lane({}, {"number": 1})  # the single path: no lane, nothing to name


def test_the_tag_is_a_sentence_and_names_no_pull_request():
    line = "task 901 — Bash: pytest -q"
    assert progress_bridge.is_telling(line)
    assert "#" not in cycle_graph.LANE_TAG  # the theater reads PR numbers off "#N"


def test_the_station_shows_each_dev_s_task_and_last_line():
    cycle_id = "lanes-test-0001"
    since = time.time() - 1
    try:
        progress_bridge.record_live_progress(cycle_id, "Dev", "task 900 — Edit src/schemas/venue.py")
        progress_bridge.record_live_progress(cycle_id, "Dev", "task 901 — Bash: pytest -q")
        progress_bridge.record_live_progress(cycle_id, "Dev", "task 900 — Running tests")
        progress_bridge.record_live_progress(cycle_id, "Dev", "Up to 2 tasks side by side")

        lanes = progress_bridge.get_live_lanes(cycle_id, since=since)
        assert [(lane["task"], lane["message"]) for lane in lanes] == [
            (900, "Running tests"), (901, "Bash: pytest -q")]
        assert progress_bridge.get_live_lanes(cycle_id, since=time.time() + 60) == []  # an earlier iteration's
        assert progress_bridge.get_live_lanes("another") == []
    finally:
        for key in [k for k in progress_bridge._LIVE_LANES if k[0] == cycle_id]:
            progress_bridge._LIVE_LANES.pop(key)
        for key in [k for k in progress_bridge._LIVE_PROGRESS if k[0] == cycle_id]:
            progress_bridge._LIVE_PROGRESS.pop(key)
