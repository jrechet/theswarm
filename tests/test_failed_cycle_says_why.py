"""A failed cycle says why: on its row, in the API, in the harness.

On 2026-09-25 the continuation 46ff31375dce was killed by a second deploy,
and the boot resumer declined a second resume (one per cycle, by design).
Its row read "failed" with nothing else: the API's `error` was null, the
harness printed "FAIL — cycle failed", and the reason lived in one log
line ("resuming 0"). The tracker knew a failure's text only until the next
restart; the cycles table had no place for it.
"""

from __future__ import annotations

import importlib.util
import pathlib
from datetime import datetime, timezone

import pytest

from theswarm.application.services import cycle_resumer
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "why.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


def _running(cycle_id: str, triggered_by: str = "web") -> Cycle:
    return Cycle(
        id=CycleId(cycle_id), project_id="jrechet/concert-tour-app",
        status=CycleStatus.RUNNING, triggered_by=triggered_by,
        started_at=datetime.now(timezone.utc),
    )


# ── The row ────────────────────────────────────────────────────────────


async def test_the_row_keeps_the_error(repo):
    await repo.save(_running("aaaaaaaaaaaa"))
    await repo.set_error("aaaaaaaaaaaa", "RuntimeError: phase dev_loop timed out")

    cycle = await repo.get(CycleId("aaaaaaaaaaaa"))

    assert cycle.error == "RuntimeError: phase dev_loop timed out"


async def test_a_later_save_keeps_the_error(repo):
    from dataclasses import replace

    await repo.save(_running("aaaaaaaaaaaa"))
    await repo.set_error("aaaaaaaaaaaa", "boom")
    cycle = await repo.get(CycleId("aaaaaaaaaaaa"))

    await repo.save(replace(cycle, total_cost_usd=1.5))

    assert (await repo.get(CycleId("aaaaaaaaaaaa"))).error == "boom"


async def test_an_existing_database_gains_the_column(tmp_path):
    import aiosqlite

    path = tmp_path / "old.db"
    conn = await init_db(str(path))
    await conn.close()
    async with aiosqlite.connect(str(path)) as raw:
        await raw.execute("ALTER TABLE cycles DROP COLUMN error")
        await raw.commit()

    conn = await init_db(str(path))
    cursor = await conn.execute("PRAGMA table_info(cycles)")
    columns = {row[1] for row in await cursor.fetchall()}
    await conn.close()

    assert "error" in columns


async def test_a_failed_event_writes_its_error_on_the_row(repo):
    from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
    from theswarm.domain.cycles.events import CycleFailed

    await repo.save(_running("aaaaaaaaaaaa"))
    handler = CyclePersistenceHandler(repo)

    await handler.handle(CycleFailed(
        cycle_id=CycleId("aaaaaaaaaaaa"), project_id="p",
        error="ClaudeFatalError: subscription window exhausted",
    ))

    cycle = await repo.get(CycleId("aaaaaaaaaaaa"))
    assert cycle.status == CycleStatus.FAILED
    assert cycle.error == "ClaudeFatalError: subscription window exhausted"


async def test_the_boot_reap_says_a_restart_ended_it(repo):
    await repo.save(_running("aaaaaaaaaaaa"))

    await repo.reap_orphans(max_age_seconds=0, reason=cycle_resumer.RESTART_REASON)

    cycle = await repo.get(CycleId("aaaaaaaaaaaa"))
    assert cycle.error == cycle_resumer.RESTART_REASON
    assert cycle.phases[-1].summary == cycle_resumer.RESTART_REASON


async def test_the_periodic_reap_keeps_its_own_words(repo):
    await repo.save(_running("aaaaaaaaaaaa"))

    await repo.reap_orphans(max_age_seconds=0)

    assert "Orphaned" in (await repo.get(CycleId("aaaaaaaaaaaa"))).error


# ── The resumer's reasons ──────────────────────────────────────────────


def _item(cycle_id: str, **overrides) -> dict:
    return {
        "cycle_id": cycle_id, "repo": "jrechet/concert-tour-app",
        "triggered_by": "web", "resume_from": "qa", "issue_number": 344,
        **overrides,
    }


def test_a_resumed_cycle_needs_no_reason():
    items = [_item("aaaaaaaaaaaa")]
    plans = cycle_resumer.plan_resumes(items)

    assert cycle_resumer.not_resumed_reasons(items, plans) == {}


def test_a_second_interruption_says_a_person_must_look():
    items = [_item("46ff31375dce", triggered_by="auto-resume:1")]

    reasons = cycle_resumer.not_resumed_reasons(items, cycle_resumer.plan_resumes(items))

    reason = reasons["46ff31375dce"]
    assert reason.startswith(cycle_resumer.RESTART_REASON)
    assert "already an automatic resume" in reason


def test_a_cycle_with_nothing_finished_says_so():
    items = [_item("aaaaaaaaaaaa", resume_from=None)]

    reasons = cycle_resumer.not_resumed_reasons(items, cycle_resumer.plan_resumes(items))

    assert "no phase had finished" in reasons["aaaaaaaaaaaa"]


def test_a_cycle_without_a_graph_thread_says_so():
    items = [_item("aaaaaaaaaaaa", resume_from=None,
                   not_resumable="no graph checkpoint (it predates the durable cycle)")]

    reasons = cycle_resumer.not_resumed_reasons(items, cycle_resumer.plan_resumes(items))

    assert "no graph checkpoint" in reasons["aaaaaaaaaaaa"]


def test_the_boot_cap_says_so():
    items = [_item(f"{n:012d}") for n in range(cycle_resumer.MAX_RESUMES_PER_BOOT + 1)]

    reasons = cycle_resumer.not_resumed_reasons(items, cycle_resumer.plan_resumes(items))

    (reason,) = reasons.values()
    assert "at once" in reason


async def test_the_boot_writes_the_reasons_down(repo):
    await repo.save(_running("46ff31375dce", triggered_by="auto-resume:1"))
    items = [_item("46ff31375dce", triggered_by="auto-resume:1")]
    await repo.reap_orphans(max_age_seconds=0, reason=cycle_resumer.RESTART_REASON)

    await cycle_resumer.record_not_resumed(repo, items, cycle_resumer.plan_resumes(items))

    assert "already an automatic resume" in (await repo.get(CycleId("46ff31375dce"))).error


async def test_collecting_marks_a_cycle_without_a_graph_thread(repo):
    from types import SimpleNamespace

    await repo.save(_running("aaaaaaaaaaaa"))

    class Checkpoints:
        async def last_ok(self, cycle_id):
            return SimpleNamespace(next_phase="qa")

    class NoThreads:
        async def aget_tuple(self, config):
            return None

    (item,) = await cycle_resumer.collect_interrupted(repo, Checkpoints(), graph_checkpointer=NoThreads())

    assert item["resume_from"] is None
    assert "no graph checkpoint" in item["not_resumable"]


# ── The API ────────────────────────────────────────────────────────────


def test_the_api_answer_carries_the_rows_error():
    from theswarm.application.dto import CycleDTO
    from theswarm.presentation.web.routes.api import _cycle_dto_to_unified_json

    dto = CycleDTO(
        id="46ff31375dce", project_id="p", status="failed", triggered_by="auto-resume:1",
        started_at=None, completed_at=None, total_tokens=0, total_cost_usd=0.0,
        prs_opened=[], prs_merged=[], phases=[], error="Interrupted by a restart",
    )

    assert _cycle_dto_to_unified_json(dto)["error"] == "Interrupted by a restart"


async def test_the_status_query_passes_the_error_through(repo):
    from theswarm.application.queries.get_cycle_status import GetCycleStatusQuery

    await repo.save(_running("aaaaaaaaaaaa"))
    await repo.set_error("aaaaaaaaaaaa", "boom")

    dto = await GetCycleStatusQuery(repo).execute("aaaaaaaaaaaa")

    assert dto.error == "boom"


# ── The harness ────────────────────────────────────────────────────────


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_why", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_harness_fail_line_carries_the_reason():
    harness = _harness()

    reasons = harness.failure_reasons(
        "failed", new_prs=[348], left=[], error="Interrupted by a restart; not resumed — …",
    )

    assert reasons == ["cycle failed: Interrupted by a restart; not resumed — …"]


def test_the_harness_fail_line_without_a_reason_is_unchanged():
    harness = _harness()

    assert harness.failure_reasons("failed", new_prs=[], left=[347]) == [
        "cycle failed", "no pull request produced", "1 sub-task(s) left unbuilt",
    ]


# ── Continuations (found on 46ff31375dce) ──────────────────────────────


def test_a_continuation_s_reason_is_the_depth_cap_even_with_no_phase_recorded():
    """46ff31375dce had finished its dev loop, but no phase checkpoint was
    recorded under its id: the reason is the cap, not "nothing finished"."""
    items = [_item("46ff31375dce", triggered_by="auto-resume:1", resume_from=None)]

    reasons = cycle_resumer.not_resumed_reasons(items, cycle_resumer.plan_resumes(items))

    assert "already an automatic resume" in reasons["46ff31375dce"]


async def test_a_continuation_reads_its_origin_s_graph_thread(repo):
    """A continuation runs on the thread of the cycle it continues (V2 M4)."""
    from types import SimpleNamespace

    await repo.save(_running("092596248fb9"))
    await repo.mark_resumed("092596248fb9", "46ff31375dce")
    await repo.save(_running("46ff31375dce", triggered_by="auto-resume:1"))
    await repo.reap_orphans(max_age_seconds=0)  # the origin is failed, not running
    await repo.save(_running("46ff31375dce", triggered_by="auto-resume:1"))

    asked: list[str] = []

    class Checkpoints:
        async def last_ok(self, cycle_id):
            return SimpleNamespace(next_phase="qa")

    class Threads:
        async def aget_tuple(self, config):
            thread_id = config["configurable"]["thread_id"]
            asked.append(thread_id)
            if thread_id != "092596248fb9":
                return None
            return SimpleNamespace(checkpoint={"channel_values": {"target_issue": 344}})

    (item,) = await cycle_resumer.collect_interrupted(repo, Checkpoints(), graph_checkpointer=Threads())

    assert asked == ["092596248fb9"]
    assert item["not_resumable"] == "" and item["issue_number"] == 344


async def test_the_origin_of_a_chain_is_its_first_cycle(repo):
    for cycle_id in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"):
        await repo.save(_running(cycle_id))
    await repo.mark_resumed("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    await repo.mark_resumed("bbbbbbbbbbbb", "cccccccccccc")

    assert await repo.origin_of("cccccccccccc") == "aaaaaaaaaaaa"
    assert await repo.origin_of("aaaaaaaaaaaa") == "aaaaaaaaaaaa"


async def test_a_continuation_records_its_phases(monkeypatch):
    """The resume launcher never passed the phase-checkpoint repository:
    46ff31375dce and 1bb1bfcb0d96 recorded no phase at all."""
    from types import SimpleNamespace

    import theswarm.api as api
    from theswarm.application.services.cycle_resumer import ResumePlan
    from theswarm.presentation.web import server

    launched: dict = {}

    async def fake_run(cycle_id, repo, *args, **kwargs):
        launched.update(kwargs)

    monkeypatch.setattr(api, "run_api_cycle", fake_run)

    class Repo:
        async def mark_resumed(self, old, new):
            pass

    checkpoints = object()
    app = SimpleNamespace(state=SimpleNamespace(checkpoint_repo=checkpoints))
    plan = ResumePlan(cycle_id="092596248fb9", repo="jrechet/concert-tour-app",
                      resume_from="dev_loop", depth=1)

    await server._launch_resume(app, plan, [], None, Repo(), None)
    import asyncio
    await asyncio.sleep(0)

    assert launched["checkpoint_repo"] is checkpoints
