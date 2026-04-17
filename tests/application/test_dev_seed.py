"""Tests for dev-seed service."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.application.services.dev_seed import SEED_PROJECT_ID, seed_dev_data
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "seed.db"))
    yield conn
    await conn.close()


async def test_seed_creates_project_when_missing(db):
    project_repo = SQLiteProjectRepository(db)

    result = await seed_dev_data(db, project_repo, count=1)

    assert result.project_created is True
    assert result.reports_inserted == 1
    project = await project_repo.get(SEED_PROJECT_ID)
    assert project is not None


async def test_seed_inserts_requested_count(db):
    project_repo = SQLiteProjectRepository(db)

    await seed_dev_data(db, project_repo, count=4)

    reports = await SQLiteReportRepository(db).list_by_project(SEED_PROJECT_ID)
    assert len(reports) == 4


async def test_seed_is_idempotent(db):
    project_repo = SQLiteProjectRepository(db)

    r1 = await seed_dev_data(db, project_repo, count=2)
    r2 = await seed_dev_data(db, project_repo, count=2)

    assert r1.project_created is True
    assert r2.project_created is False
    reports = await SQLiteReportRepository(db).list_by_project(SEED_PROJECT_ID)
    assert len(reports) == 2  # INSERT OR REPLACE keeps one row per ID


async def test_seed_reset_deletes_prior_rows(db):
    project_repo = SQLiteProjectRepository(db)

    await seed_dev_data(db, project_repo, count=3)
    result = await seed_dev_data(db, project_repo, count=1, reset=True)

    assert result.reports_deleted == 3
    reports = await SQLiteReportRepository(db).list_by_project(SEED_PROJECT_ID)
    assert len(reports) == 1


async def test_seed_report_has_stories_gates_artifacts(db):
    project_repo = SQLiteProjectRepository(db)
    fixed = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)

    await seed_dev_data(db, project_repo, count=1, now=fixed)

    reports = await SQLiteReportRepository(db).list_by_project(SEED_PROJECT_ID)
    r = reports[0]
    assert len(r.stories) == 1
    assert r.stories[0].ticket_id.startswith("SEED-")
    assert len(r.quality_gates) == 3
    assert r.artifacts
    assert r.created_at == fixed
