"""Tests for seed_self — registers TheSwarm as a project and seeds per-sprint demos."""

from __future__ import annotations

import pytest

from theswarm.application.services.self_seed import (
    _PROJECT_ID,
    _SPRINTS,
    seed_self,
)
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "self_seed.db"))
    yield conn
    await conn.close()


async def test_seed_self_creates_project(db):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    result = await seed_self(project_repo, report_repo)

    assert result.project_created is True
    project = await project_repo.get(_PROJECT_ID)
    assert project is not None
    assert str(project.repo) == "jrechet/theswarm"


async def test_seed_self_inserts_one_report_per_sprint(db):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    result = await seed_self(project_repo, report_repo)

    assert len(result.reports_saved) == len(_SPRINTS)
    reports = await report_repo.list_by_project(_PROJECT_ID, limit=50)
    assert len(reports) == len(_SPRINTS)


async def test_seed_self_is_idempotent(db):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    r1 = await seed_self(project_repo, report_repo)
    r2 = await seed_self(project_repo, report_repo)

    assert r1.project_created is True
    assert r2.project_created is False
    reports = await report_repo.list_by_project(_PROJECT_ID, limit=50)
    assert len(reports) == len(_SPRINTS)


async def test_seed_self_reports_have_stories_and_gates(db):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    await seed_self(project_repo, report_repo)
    reports = await report_repo.list_by_project(_PROJECT_ID, limit=50)

    assert all(len(r.stories) >= 3 for r in reports)
    assert all(len(r.quality_gates) == 4 for r in reports)
    assert all(r.all_gates_pass for r in reports)


async def test_seed_self_no_video_when_source_missing(db, tmp_path):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    empty = tmp_path / "empty"
    empty.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    result = await seed_self(
        project_repo,
        report_repo,
        video_source_dir=empty,
        artifacts_base_dir=artifacts,
    )

    assert result.videos_attached == ()


async def test_seed_self_attaches_sprint_a_video(db, tmp_path):
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    video_src = tmp_path / "videos"
    video_src.mkdir()
    fake = video_src / "sprint-A.webm"
    fake.write_bytes(b"fake-webm-bytes")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    result = await seed_self(
        project_repo,
        report_repo,
        video_source_dir=video_src,
        artifacts_base_dir=artifacts,
    )

    assert len(result.videos_attached) == 1
    attached_rel = result.videos_attached[0]
    assert attached_rel.endswith("sprint-A.webm")

    copied = artifacts / attached_rel
    assert copied.is_file()
    assert copied.read_bytes() == b"fake-webm-bytes"

    reports = await report_repo.list_by_project(_PROJECT_ID, limit=50)
    sprint_a = next(r for r in reports if r.id == "theswarm-sprint-a")
    assert len(sprint_a.artifacts) == 1
    assert sprint_a.artifacts[0].type.value == "video"
    assert sprint_a.artifacts[0].path.endswith("sprint-A.webm")


async def test_seed_self_idempotent_video_copy(db, tmp_path):
    """Re-running with the same video doesn't duplicate or error."""
    project_repo = SQLiteProjectRepository(db)
    report_repo = SQLiteReportRepository(db)

    video_src = tmp_path / "videos"
    video_src.mkdir()
    (video_src / "sprint-A.webm").write_bytes(b"v1")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    r1 = await seed_self(
        project_repo, report_repo,
        video_source_dir=video_src, artifacts_base_dir=artifacts,
    )
    r2 = await seed_self(
        project_repo, report_repo,
        video_source_dir=video_src, artifacts_base_dir=artifacts,
    )

    assert r1.videos_attached == r2.videos_attached
