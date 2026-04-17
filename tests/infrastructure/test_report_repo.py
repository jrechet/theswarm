"""Tests for SQLiteReportRepository."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    DiffHighlight,
    QualityGate,
    QualityStatus,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository


@pytest.fixture
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    yield SQLiteReportRepository(conn)
    await conn.close()


def _make_report(
    report_id: str = "rpt-1",
    cycle_id: str = "cycle-1",
    project_id: str = "proj-1",
    stories: tuple[StoryReport, ...] = (),
    quality_gates: tuple[QualityGate, ...] = (),
    agent_learnings: tuple[str, ...] = (),
    artifacts: tuple[Artifact, ...] = (),
    summary: ReportSummary | None = None,
) -> DemoReport:
    return DemoReport(
        id=report_id,
        cycle_id=CycleId(cycle_id),
        project_id=project_id,
        created_at=datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc),
        summary=summary or ReportSummary(
            stories_completed=2,
            stories_total=3,
            prs_merged=1,
            tests_passing=40,
            tests_total=42,
            coverage_percent=85.5,
            security_critical=0,
            security_medium=1,
            cost_usd=1.23,
        ),
        stories=stories,
        quality_gates=quality_gates,
        agent_learnings=agent_learnings,
        artifacts=artifacts,
    )


class TestSaveAndGet:
    async def test_save_and_get_minimal(self, repo):
        report = _make_report()
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded is not None
        assert loaded.id == "rpt-1"
        assert loaded.project_id == "proj-1"
        assert str(loaded.cycle_id) == "cycle-1"

    async def test_get_nonexistent(self, repo):
        result = await repo.get("nope")
        assert result is None

    async def test_roundtrip_summary(self, repo):
        report = _make_report()
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded.summary.stories_completed == 2
        assert loaded.summary.stories_total == 3
        assert loaded.summary.prs_merged == 1
        assert loaded.summary.tests_passing == 40
        assert loaded.summary.tests_total == 42
        assert loaded.summary.coverage_percent == 85.5
        assert loaded.summary.security_critical == 0
        assert loaded.summary.security_medium == 1
        assert loaded.summary.cost_usd == 1.23

    async def test_roundtrip_stories(self, repo):
        story = StoryReport(
            title="Add login page",
            ticket_id="GH-42",
            pr_number=7,
            pr_url="https://github.com/o/r/pull/7",
            status="completed",
            files_changed=3,
            lines_added=120,
            lines_removed=5,
            screenshots_before=(
                Artifact(type=ArtifactType.SCREENSHOT, label="before", path="b.png"),
            ),
            screenshots_after=(
                Artifact(type=ArtifactType.SCREENSHOT, label="after", path="a.png"),
            ),
            video=Artifact(type=ArtifactType.VIDEO, label="demo", path="d.webm", size_bytes=1000),
            diff_highlights=(
                DiffHighlight(file_path="src/login.py", hunk="@@ -1,3 +1,5 @@", annotation="New route"),
            ),
        )
        report = _make_report(stories=(story,))
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert len(loaded.stories) == 1
        s = loaded.stories[0]
        assert s.title == "Add login page"
        assert s.ticket_id == "GH-42"
        assert s.pr_number == 7
        assert s.pr_url == "https://github.com/o/r/pull/7"
        assert s.files_changed == 3
        assert s.lines_added == 120
        assert s.lines_removed == 5
        assert len(s.screenshots_before) == 1
        assert s.screenshots_before[0].label == "before"
        assert len(s.screenshots_after) == 1
        assert s.video is not None
        assert s.video.size_bytes == 1000
        assert len(s.diff_highlights) == 1
        assert s.diff_highlights[0].annotation == "New route"

    async def test_roundtrip_quality_gates(self, repo):
        gates = (
            QualityGate(name="tests", status=QualityStatus.PASS, detail="42/42"),
            QualityGate(name="security", status=QualityStatus.WARN, detail="1 medium"),
        )
        report = _make_report(quality_gates=gates)
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert len(loaded.quality_gates) == 2
        assert loaded.quality_gates[0].status == QualityStatus.PASS
        assert loaded.quality_gates[1].status == QualityStatus.WARN

    async def test_roundtrip_learnings(self, repo):
        report = _make_report(agent_learnings=("Use pytest-asyncio", "Pin deps"))
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded.agent_learnings == ("Use pytest-asyncio", "Pin deps")

    async def test_roundtrip_top_level_artifacts(self, repo):
        arts = (
            Artifact(type=ArtifactType.LOG, label="build", path="build.log", size_bytes=500),
        )
        report = _make_report(artifacts=arts)
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert len(loaded.artifacts) == 1
        assert loaded.artifacts[0].label == "build"
        assert loaded.artifacts[0].size_bytes == 500

    async def test_save_replaces_existing(self, repo):
        r1 = _make_report(summary=ReportSummary(cost_usd=1.0))
        await repo.save(r1)
        r2 = _make_report(summary=ReportSummary(cost_usd=2.0))
        await repo.save(r2)
        loaded = await repo.get("rpt-1")
        assert loaded.summary.cost_usd == 2.0


class TestListByProject:
    async def test_list_empty(self, repo):
        result = await repo.list_by_project("proj-1")
        assert result == []

    async def test_list_returns_matching(self, repo):
        await repo.save(_make_report("r1", project_id="proj-1"))
        await repo.save(_make_report("r2", project_id="proj-2"))
        result = await repo.list_by_project("proj-1")
        assert len(result) == 1
        assert result[0].id == "r1"

    async def test_list_respects_limit(self, repo):
        for i in range(5):
            await repo.save(_make_report(f"r{i}", project_id="p"))
        result = await repo.list_by_project("p", limit=2)
        assert len(result) == 2


class TestListByCycle:
    async def test_list_by_cycle_empty(self, repo):
        result = await repo.list_by_cycle("c-none")
        assert result == []

    async def test_list_by_cycle_returns_matching(self, repo):
        await repo.save(_make_report("r1", cycle_id="c-1"))
        await repo.save(_make_report("r2", cycle_id="c-2"))
        result = await repo.list_by_cycle("c-1")
        assert len(result) == 1
        assert result[0].id == "r1"


class TestCreatedAtParsing:
    async def test_created_at_roundtrip(self, repo):
        report = _make_report()
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded.created_at.year == 2026
        assert loaded.created_at.month == 4
        assert loaded.created_at.tzinfo is not None


# Regression: the /demos/ browse page returned 500 because _row_to_report
# raised KeyError when reports written by older pipeline versions were missing
# fields like 'ticket_id' or 'files_changed'. The deserializer must tolerate
# any subset of known fields.
class TestPartialDataTolerance:
    """Deserializer must never crash on reports written with partial data."""

    async def test_loads_report_with_empty_stories(self, repo):
        report = _make_report(stories=())
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded is not None
        assert loaded.stories == ()

    async def test_loads_report_with_empty_gates(self, repo):
        report = _make_report(quality_gates=())
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded is not None
        assert loaded.quality_gates == ()

    async def test_loads_report_with_empty_artifacts(self, repo):
        report = _make_report(artifacts=())
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded is not None
        assert loaded.artifacts == ()

    async def test_loads_report_with_empty_learnings(self, repo):
        report = _make_report(agent_learnings=())
        await repo.save(report)
        loaded = await repo.get("rpt-1")
        assert loaded is not None
        assert loaded.agent_learnings == ()

    async def test_loads_row_with_missing_story_fields(self, tmp_path):
        """Stories written without ticket_id, pr_url, file stats must still load."""
        import json as _json

        db_path = str(tmp_path / "partial.db")
        from theswarm.infrastructure.persistence.sqlite_repos import init_db
        conn = await init_db(db_path)
        partial_repo = SQLiteReportRepository(conn)

        partial_story = {
            "title": "Legacy story with bare fields",
            "screenshots_before": [],
            "screenshots_after": [],
            "diff_highlights": [{}],
        }

        await conn.execute(
            """INSERT INTO reports (id, cycle_id, project_id, summary_json,
                stories_json, quality_json, learnings_json, artifacts_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "partial-1",
                "cyc-x",
                "proj-x",
                "{}",
                _json.dumps([partial_story]),
                "[]",
                "[]",
                "[]",
                "2026-04-17T00:00:00+00:00",
            ),
        )
        await conn.commit()

        loaded = await partial_repo.get("partial-1")
        assert loaded is not None
        assert len(loaded.stories) == 1
        s = loaded.stories[0]
        assert s.title == "Legacy story with bare fields"
        assert s.ticket_id == ""
        assert s.pr_url == ""
        assert s.files_changed == 0
        assert len(s.diff_highlights) == 1
        assert s.diff_highlights[0].file_path == ""
        assert s.diff_highlights[0].hunk == ""
        await conn.close()

    async def test_loads_row_with_empty_json_fields(self, tmp_path):
        """Rows with empty-string *_json columns must load as empty collections.

        Schema has NOT NULL DEFAULT '{}'|'[]' so true NULLs are impossible,
        but legacy rows can still carry empty strings which the deserializer
        must treat as falsy.
        """
        db_path = str(tmp_path / "empty.db")
        from theswarm.infrastructure.persistence.sqlite_repos import init_db
        conn = await init_db(db_path)
        partial_repo = SQLiteReportRepository(conn)

        await conn.execute(
            """INSERT INTO reports (id, cycle_id, project_id, summary_json,
                stories_json, quality_json, learnings_json, artifacts_json, created_at)
                VALUES (?, ?, ?, '', '', '', '', '', ?)""",
            ("empty-1", "cyc-y", "proj-y", "2026-04-17T00:00:00+00:00"),
        )
        await conn.commit()

        loaded = await partial_repo.get("empty-1")
        assert loaded is not None
        assert loaded.stories == ()
        assert loaded.quality_gates == ()
        assert loaded.agent_learnings == ()
        assert loaded.artifacts == ()
        assert loaded.summary.stories_completed == 0
        assert loaded.summary.coverage_percent == 0.0
        await conn.close()

    async def test_loads_row_with_missing_gate_detail(self, tmp_path):
        """Quality gates written without 'detail' field must load with default."""
        import json as _json
        db_path = str(tmp_path / "gate.db")
        from theswarm.infrastructure.persistence.sqlite_repos import init_db
        conn = await init_db(db_path)
        partial_repo = SQLiteReportRepository(conn)

        gates = [{"name": "tests", "status": "pass"}]
        await conn.execute(
            """INSERT INTO reports (id, cycle_id, project_id, summary_json,
                stories_json, quality_json, learnings_json, artifacts_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "gate-1",
                "cyc-z",
                "proj-z",
                "{}",
                "[]",
                _json.dumps(gates),
                "[]",
                "[]",
                "2026-04-17T00:00:00+00:00",
            ),
        )
        await conn.commit()

        loaded = await partial_repo.get("gate-1")
        assert loaded is not None
        assert len(loaded.quality_gates) == 1
        assert loaded.quality_gates[0].name == "tests"
        assert loaded.quality_gates[0].detail == ""
        await conn.close()
