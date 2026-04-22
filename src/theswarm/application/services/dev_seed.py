"""Developer seed: populate a dev DB with synthetic demo data.

Used by `theswarm dev-seed` so the dashboard shows a believable example without
running full agent cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiosqlite

from theswarm.application.commands.create_project import (
    CreateProjectCommand,
    CreateProjectHandler,
)
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    DiffHighlight,
    QualityGate,
    QualityStatus,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository

SEED_PROJECT_ID = "dev-seed-demo"
SEED_REPO = "example/dev-seed-demo"


@dataclass(frozen=True)
class SeedResult:
    project_created: bool
    reports_deleted: int
    reports_inserted: int


_STORIES = [
    (
        "SEED-1",
        "Add dark mode toggle",
        "src/ui/ThemeToggle.tsx",
        "+ const [theme, setTheme] = useState('dark')",
        "New stateful toggle with localStorage persistence",
    ),
    (
        "SEED-2",
        "Cache API responses for 60s",
        "src/lib/cache.ts",
        "+ const cache = new LRUCache({ ttl: 60_000 })",
        "Cuts repeat-request latency",
    ),
    (
        "SEED-3",
        "Fix NPE in filter parser",
        "src/filters/parser.py",
        "+ if not tokens: return EmptyFilter()",
        "Guard against empty token list",
    ),
]


def _build_report(
    index: int,
    when: datetime,
    project_id: str,
) -> DemoReport:
    ticket_id, title, file_path, hunk, annotation = _STORIES[index % len(_STORIES)]
    story = StoryReport(
        ticket_id=ticket_id,
        title=title,
        status="completed",
        pr_number=100 + index,
        pr_url=f"https://github.com/{SEED_REPO}/pull/{100 + index}",
        files_changed=3,
        lines_added=42 - index,
        lines_removed=7 + index,
        screenshots_before=(
            Artifact(
                type=ArtifactType.SCREENSHOT,
                label="Before",
                path=f"seed/{ticket_id}-before.png",
                size_bytes=1234,
            ),
        ),
        screenshots_after=(
            Artifact(
                type=ArtifactType.SCREENSHOT,
                label="After",
                path=f"seed/{ticket_id}-after.png",
                size_bytes=2345,
            ),
        ),
        diff_highlights=(
            DiffHighlight(file_path=file_path, hunk=hunk, annotation=annotation),
        ),
    )
    gates = (
        QualityGate(name="Unit tests", status=QualityStatus.PASS, detail="42/42 passing"),
        QualityGate(name="E2E tests", status=QualityStatus.PASS, detail="5/5 passing"),
        QualityGate(
            name="Coverage",
            status=QualityStatus.PASS,
            detail=f"{82.0 + index:.1f}% (target 80%)",
        ),
    )
    summary = ReportSummary(
        stories_completed=1,
        stories_total=1,
        prs_merged=1,
        tests_passing=42,
        tests_total=42,
        coverage_percent=82.0 + index,
        cost_usd=0.05 + index * 0.01,
    )
    return DemoReport(
        id=f"dev-seed-report-{index + 1}",
        cycle_id=CycleId(f"dev-seed-cycle-{index + 1}"),
        project_id=project_id,
        created_at=when,
        summary=summary,
        stories=(story,),
        quality_gates=gates,
        agent_learnings=(f"Lesson {index + 1}: keep scope small",),
        artifacts=(
            Artifact(
                type=ArtifactType.SCREENSHOT,
                label="Dashboard",
                path=f"seed/{ticket_id}-dashboard.png",
                size_bytes=3456,
            ),
        ),
    )


async def seed_dev_data(
    conn: aiosqlite.Connection,
    project_repo: ProjectRepository,
    *,
    count: int = 3,
    reset: bool = False,
    project_id: str = SEED_PROJECT_ID,
    now: datetime | None = None,
) -> SeedResult:
    """Insert synthetic demo reports into the DB.

    Idempotent: reruns replace the prior seed rows by ID. `reset=True` wipes
    all seed rows for this project before inserting.
    """
    project_created = False
    if await project_repo.get(project_id) is None:
        from theswarm.application.services.role_assignment_service import (
            RoleAssignmentService,
        )
        from theswarm.infrastructure.agents.role_assignment_repo import (
            SQLiteRoleAssignmentRepository,
        )

        role_service = RoleAssignmentService(SQLiteRoleAssignmentRepository(conn))
        await CreateProjectHandler(project_repo, role_service=role_service).handle(
            CreateProjectCommand(project_id=project_id, repo=SEED_REPO, framework="auto"),
        )
        project_created = True

    reports_deleted = 0
    if reset:
        cursor = await conn.execute(
            "DELETE FROM reports WHERE project_id = ?", (project_id,),
        )
        reports_deleted = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        await conn.commit()

    report_repo = SQLiteReportRepository(conn)
    base = now or datetime.now(timezone.utc)
    for i in range(count):
        await report_repo.save(_build_report(i, base - timedelta(days=i), project_id))

    return SeedResult(
        project_created=project_created,
        reports_deleted=reports_deleted,
        reports_inserted=count,
    )
