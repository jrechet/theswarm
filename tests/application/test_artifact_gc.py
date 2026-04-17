"""Tests for artifact GC service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from theswarm.application.services.artifact_gc import (
    collect_live_cycle_ids,
    gc_artifacts,
)
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "gc.db"))
    yield conn
    await conn.close()


def _make_report(cycle_id: str, *, project_id: str = "p1") -> DemoReport:
    return DemoReport(
        id=f"report-{cycle_id}",
        cycle_id=CycleId(cycle_id),
        project_id=project_id,
        created_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        summary=ReportSummary(),
        stories=(),
        quality_gates=(),
        agent_learnings=(),
        artifacts=(),
    )


def _seed_artifact_dir(base: Path, cycle_id: str, *, size: int = 100) -> None:
    d = base / cycle_id / "screenshot"
    d.mkdir(parents=True, exist_ok=True)
    (d / "shot.png").write_bytes(b"x" * size)


async def test_collect_live_cycle_ids_empty(db):
    live = await collect_live_cycle_ids(db)
    assert live == set()


async def test_collect_live_cycle_ids_returns_distinct(db):
    repo = SQLiteReportRepository(db)
    await repo.save(_make_report("cyc-1"))
    await repo.save(_make_report("cyc-2"))

    live = await collect_live_cycle_ids(db)
    assert live == {"cyc-1", "cyc-2"}


async def test_gc_missing_artifact_dir_is_noop(db, tmp_path):
    result = await gc_artifacts(db, str(tmp_path / "does-not-exist"), dry_run=True)
    assert result.scanned_dirs == 0
    assert result.orphaned_dirs == ()
    assert result.bytes_reclaimed == 0


async def test_gc_identifies_orphans_dry_run(db, tmp_path):
    repo = SQLiteReportRepository(db)
    await repo.save(_make_report("cyc-live"))

    artifacts = tmp_path / "artifacts"
    _seed_artifact_dir(artifacts, "cyc-live", size=50)
    _seed_artifact_dir(artifacts, "cyc-orphan-1", size=100)
    _seed_artifact_dir(artifacts, "cyc-orphan-2", size=200)

    result = await gc_artifacts(db, str(artifacts), dry_run=True)

    assert result.scanned_dirs == 3
    assert result.live_cycle_ids == 1
    assert set(result.orphaned_dirs) == {"cyc-orphan-1", "cyc-orphan-2"}
    assert result.bytes_reclaimed == 300
    assert result.deleted is False
    assert (artifacts / "cyc-orphan-1").exists()


async def test_gc_deletes_orphans_when_not_dry_run(db, tmp_path):
    repo = SQLiteReportRepository(db)
    await repo.save(_make_report("cyc-live"))

    artifacts = tmp_path / "artifacts"
    _seed_artifact_dir(artifacts, "cyc-live")
    _seed_artifact_dir(artifacts, "cyc-orphan")

    result = await gc_artifacts(db, str(artifacts), dry_run=False)

    assert result.deleted is True
    assert result.orphaned_dirs == ("cyc-orphan",)
    assert not (artifacts / "cyc-orphan").exists()
    assert (artifacts / "cyc-live").exists()


async def test_gc_ignores_non_directory_entries(db, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "stray.txt").write_bytes(b"ignored")

    result = await gc_artifacts(db, str(artifacts), dry_run=True)
    assert result.scanned_dirs == 0
