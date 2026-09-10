"""A deploy must not throw away what a running cycle had achieved.

The tracker lives in memory, so every container replacement killed the
cycles in flight — repeatedly, today. Checkpoints and
``run_daily_cycle(resume_from=...)`` already existed; nothing used them
automatically.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.services.cycle_resumer import (
    MAX_RESUMES_PER_BOOT,
    ResumePlan,
    collect_interrupted,
    plan_resumes,
    resume_depth,
)
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    init_db,
)


def _item(cycle_id="abc", repo="jrechet/theswarm", resume_from="qa", triggered_by=""):
    return {
        "cycle_id": cycle_id, "repo": repo,
        "resume_from": resume_from, "triggered_by": triggered_by,
    }


# ── What gets resumed ──────────────────────────────────────────────────


def test_an_interrupted_cycle_resumes_from_after_its_last_good_phase():
    [plan] = plan_resumes([_item(resume_from="dev_loop")])

    assert plan.cycle_id == "abc"
    assert plan.resume_from == "dev_loop"
    assert plan.repo == "jrechet/theswarm"
    assert "abc" in plan.description


def test_a_cycle_that_finished_no_phase_is_not_resumed():
    """Nothing to continue — the reap already marked it failed, honestly."""
    assert plan_resumes([_item(resume_from=None)]) == []


def test_a_cycle_with_no_repo_is_not_resumed():
    assert plan_resumes([_item(repo="")]) == []


# ── The guards ─────────────────────────────────────────────────────────


def test_a_resume_is_not_itself_resumed():
    """Otherwise a cycle crashing on the phase it resumes into loops forever."""
    assert plan_resumes([_item(triggered_by="auto-resume:1")]) == []


def test_a_resumed_cycle_is_marked_so_the_next_boot_can_tell():
    [plan] = plan_resumes([_item()])
    assert plan.triggered_by == "auto-resume:1"
    assert resume_depth(plan.triggered_by) == 1


@pytest.mark.parametrize("triggered_by, expected", [
    ("", 0), ("web", 0), ("auto-resume:1", 1), ("auto-resume:2", 2),
    ("auto-resume:garbage", 0),
])
def test_resume_depth_reads_the_marker(triggered_by, expected):
    assert resume_depth(triggered_by) == expected


def test_a_restart_during_a_busy_period_does_not_launch_a_herd():
    many = [_item(cycle_id=f"c{i}") for i in range(10)]
    assert len(plan_resumes(many)) == MAX_RESUMES_PER_BOOT


# ── Reading them out of the database ───────────────────────────────────


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


async def _save(repo, cycle_id, status, triggered_by=""):
    await repo.save(Cycle(
        id=CycleId(cycle_id), project_id="jrechet/theswarm", status=status,
        triggered_by=triggered_by, started_at=datetime.now(timezone.utc),
    ))


async def test_list_running_returns_only_running_cycles(repo):
    await _save(repo, "aaaaaaaaaaaa", CycleStatus.RUNNING)
    await _save(repo, "bbbbbbbbbbbb", CycleStatus.COMPLETED)
    await _save(repo, "cccccccccccc", CycleStatus.FAILED)

    running = await repo.list_running()

    assert [str(c.id) for c in running] == ["aaaaaaaaaaaa"]


async def test_collect_pairs_each_cycle_with_its_checkpoint(repo):
    await _save(repo, "aaaaaaaaaaaa", CycleStatus.RUNNING, triggered_by="web")

    class _Checkpoints:
        async def last_ok(self, cycle_id):
            assert cycle_id == "aaaaaaaaaaaa"
            return type("C", (), {"next_phase": "qa"})()

    [item] = await collect_interrupted(repo, _Checkpoints())

    assert item["resume_from"] == "qa"
    assert item["triggered_by"] == "web"
    assert item["repo"] == "jrechet/theswarm"


async def test_a_broken_checkpoint_store_does_not_break_startup(repo):
    await _save(repo, "aaaaaaaaaaaa", CycleStatus.RUNNING)

    class _Broken:
        async def last_ok(self, cycle_id):
            raise RuntimeError("checkpoint table is corrupt")

    assert await collect_interrupted(repo, _Broken()) == []


async def test_no_checkpoint_repo_means_no_resume(repo):
    await _save(repo, "aaaaaaaaaaaa", CycleStatus.RUNNING)
    assert await collect_interrupted(repo, None) == []


# ── Startup order ──────────────────────────────────────────────────────


def test_startup_collects_before_it_reaps():
    """The reap flips rows to 'failed'; reading after it would find nothing."""
    from pathlib import Path

    source = Path("src/theswarm/presentation/web/server.py").read_text()
    assert source.index("collect_interrupted(") < source.index("reap_orphans(")
