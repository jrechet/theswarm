"""A finished agent stops being judged idle.

Prod cycle bc1b1e6abb82 logged "Agent 'PO' timed out after 77 warnings
(idle 3028s)" every 30 seconds for its whole run — long after the PO phase
had finished successfully. An agent was registered on its first heartbeat
and never removed, so once it stopped sending heartbeats it looked stalled
forever. The noise buried the failures worth reading.
"""

from __future__ import annotations

import asyncio

import pytest

from theswarm.application.services.watchdog import AgentWatchdog, WatchdogEvent


def _watchdog(**kw) -> tuple[AgentWatchdog, list[WatchdogEvent]]:
    seen: list[WatchdogEvent] = []

    async def record(event: WatchdogEvent) -> None:
        seen.append(event)

    defaults = dict(
        idle_threshold=0.0, check_interval=0.01, max_warnings=1,
        on_idle=record, on_timeout=record,
    )
    defaults.update(kw)
    return AgentWatchdog(**defaults), seen


async def _let_it_check(times: int = 6) -> None:
    await asyncio.sleep(0.01 * times)


# ── Retirement ─────────────────────────────────────────────────────────


async def test_a_retired_agent_is_never_reported_again():
    watchdog, seen = _watchdog()
    watchdog.heartbeat("PO", "planning")
    watchdog.retire("PO")

    await watchdog.start()
    await _let_it_check()
    await watchdog.stop()

    assert seen == []


async def test_retiring_an_unknown_role_is_harmless():
    """Phases can end before their agent ever emitted progress."""
    watchdog, _ = _watchdog()
    watchdog.retire("NeverStarted")  # must not raise


async def test_a_retired_role_can_come_back():
    """Dev is retired after each iteration and re-registers on the next."""
    watchdog, _ = _watchdog()
    watchdog.heartbeat("Dev", "iteration 1")
    watchdog.retire("Dev")
    watchdog.heartbeat("Dev", "iteration 2")

    assert "Dev" in watchdog.get_status()


async def test_retirement_leaves_other_agents_watched():
    watchdog, seen = _watchdog()
    watchdog.heartbeat("PO", "done")
    watchdog.heartbeat("Dev", "working")
    watchdog.retire("PO")

    await watchdog.start()
    await _let_it_check()
    await watchdog.stop()

    assert {e.role for e in seen} == {"Dev"}


# ── Single-fire timeout ────────────────────────────────────────────────


async def test_a_stalled_role_is_reported_once_not_every_interval():
    """Roles that emit progress without owning a phase (System, Memory) are
    never retired; without this they re-fired the same timeout forever."""
    watchdog, seen = _watchdog()
    watchdog.heartbeat("System", "checking branch protection")

    await watchdog.start()
    await _let_it_check(times=20)
    await watchdog.stop()

    assert len(seen) == 1
    assert seen[0].role == "System"


async def test_a_fresh_heartbeat_does_not_resurrect_the_alarm():
    """Recovery is real progress, not a re-alarm."""
    watchdog, seen = _watchdog()
    watchdog.heartbeat("QA", "running tests")

    await watchdog.start()
    await _let_it_check()
    watchdog.heartbeat("QA", "tests passed")
    await _let_it_check()
    await watchdog.stop()

    assert len(seen) == 1


# ── The cycle wires it ─────────────────────────────────────────────────


def test_a_finished_phase_retires_its_role():
    """_run_phase must retire in `finally`: a phase that raised is over too."""
    from pathlib import Path

    source = Path("src/theswarm/cycle.py").read_text()
    body = source[source.index("async def _run_phase"):]
    body = body[:body.index("\n    from theswarm.domain.cycles.checkpoint")]

    assert "finally:" in body
    assert "watchdog.retire(role)" in body
    assert body.index("finally:") < body.index("watchdog.retire(role)")
