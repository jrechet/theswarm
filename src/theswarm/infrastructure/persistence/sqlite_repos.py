"""SQLite implementations of domain repository ports."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
)
from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import Framework, RepoUrl, TicketSourceType
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression
from theswarm.infrastructure.persistence.migrations.v001_initial import (
    SQL as MIGRATION_V001,
)

log = logging.getLogger(__name__)

_DEFAULT_DB = "~/.swarm-data/theswarm.db"


async def init_db(db_path: str = _DEFAULT_DB) -> aiosqlite.Connection:
    """Open DB and run migrations."""
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(path))
    db.row_factory = aiosqlite.Row
    await db.executescript(MIGRATION_V001)
    await db.commit()
    return db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Project Repository ─────────────────────────────────────────────


class SQLiteProjectRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, project_id: str) -> Project | None:
        cursor = await self._db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_project(row)

    async def list_all(self) -> list[Project]:
        cursor = await self._db.execute("SELECT * FROM projects ORDER BY id")
        rows = await cursor.fetchall()
        return [self._row_to_project(r) for r in rows]

    async def save(self, project: Project) -> None:
        config_json = json.dumps({
            "max_daily_stories": project.config.max_daily_stories,
            "token_budget_po": project.config.token_budget_po,
            "token_budget_techlead": project.config.token_budget_techlead,
            "token_budget_dev": project.config.token_budget_dev,
            "token_budget_qa": project.config.token_budget_qa,
        })
        await self._db.execute(
            """INSERT OR REPLACE INTO projects
               (id, repo, default_branch, framework, ticket_source,
                team_channel, schedule, test_command, source_dir,
                config_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project.id, str(project.repo), project.default_branch,
                project.framework.value, project.ticket_source.value,
                project.team_channel, project.schedule, project.test_command,
                project.source_dir, config_json,
                project.created_at.isoformat(), _now_iso(),
            ),
        )
        await self._db.commit()

    async def delete(self, project_id: str) -> None:
        await self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await self._db.commit()

    @staticmethod
    def _row_to_project(row) -> Project:
        config_data = json.loads(row["config_json"]) if row["config_json"] else {}
        return Project(
            id=row["id"],
            repo=RepoUrl(row["repo"]),
            default_branch=row["default_branch"],
            framework=Framework(row["framework"]),
            ticket_source=TicketSourceType(row["ticket_source"]),
            team_channel=row["team_channel"],
            schedule=row["schedule"],
            test_command=row["test_command"],
            source_dir=row["source_dir"],
            config=ProjectConfig(**config_data) if config_data else ProjectConfig(),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


# ── Cycle Repository ───────────────────────────────────────────────


class SQLiteCycleRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, cycle_id: CycleId) -> Cycle | None:
        cursor = await self._db.execute(
            "SELECT * FROM cycles WHERE id = ?", (str(cycle_id),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_cycle(row)

    async def list_by_project(self, project_id: str, limit: int = 30) -> list[Cycle]:
        cursor = await self._db.execute(
            "SELECT * FROM cycles WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_cycle(r) for r in rows]

    async def save(self, cycle: Cycle) -> None:
        phases_json = json.dumps([
            {
                "phase": p.phase, "agent": p.agent,
                "started_at": p.started_at.isoformat(),
                "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                "status": p.status.value, "tokens_used": p.tokens_used,
                "cost_usd": p.cost_usd, "summary": p.summary,
            }
            for p in cycle.phases
        ])
        budgets_json = json.dumps([
            {"role": b.role, "limit": b.limit, "used": b.used}
            for b in cycle.budgets
        ])
        await self._db.execute(
            """INSERT OR REPLACE INTO cycles
               (id, project_id, status, triggered_by, started_at, completed_at,
                total_tokens, total_cost_usd, prs_opened_json, prs_merged_json,
                phases_json, budgets_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(cycle.id), cycle.project_id, cycle.status.value,
                cycle.triggered_by,
                cycle.started_at.isoformat() if cycle.started_at else None,
                cycle.completed_at.isoformat() if cycle.completed_at else None,
                cycle.total_tokens, cycle.total_cost_usd,
                json.dumps(list(cycle.prs_opened)),
                json.dumps(list(cycle.prs_merged)),
                phases_json, budgets_json,
            ),
        )
        await self._db.commit()

    @staticmethod
    def _row_to_cycle(row) -> Cycle:
        phases_data = json.loads(row["phases_json"]) if row["phases_json"] else []
        phases = tuple(
            PhaseExecution(
                phase=p["phase"], agent=p["agent"],
                started_at=datetime.fromisoformat(p["started_at"]),
                completed_at=datetime.fromisoformat(p["completed_at"]) if p.get("completed_at") else None,
                status=PhaseStatus(p["status"]),
                tokens_used=p.get("tokens_used", 0),
                cost_usd=p.get("cost_usd", 0.0),
                summary=p.get("summary", ""),
            )
            for p in phases_data
        )
        budgets_data = json.loads(row["budgets_json"]) if row["budgets_json"] else []
        budgets = tuple(
            Budget(role=b["role"], limit=b["limit"], used=b.get("used", 0))
            for b in budgets_data
        )
        return Cycle(
            id=CycleId(row["id"]),
            project_id=row["project_id"],
            status=CycleStatus(row["status"]),
            triggered_by=row["triggered_by"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            phases=phases,
            budgets=budgets,
            total_cost_usd=row["total_cost_usd"],
            prs_opened=tuple(json.loads(row["prs_opened_json"])),
            prs_merged=tuple(json.loads(row["prs_merged_json"])),
        )


# ── Memory Store ───────────────────────────────────────────────────


class SQLiteMemoryStore:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def load(self, project_id: str = "") -> list[MemoryEntry]:
        if project_id:
            cursor = await self._db.execute(
                "SELECT * FROM memory_entries WHERE project_id = ? OR project_id = '' ORDER BY created_at",
                (project_id,),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM memory_entries ORDER BY created_at",
            )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def append(self, entries: list[MemoryEntry]) -> None:
        for e in entries:
            await self._db.execute(
                """INSERT INTO memory_entries
                   (project_id, category, content, agent, cycle_date, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (e.scope.project_id, e.category.value, e.content, e.agent, e.cycle_date, e.created_at.isoformat()),
            )
        await self._db.commit()

    async def query(
        self,
        project_id: str = "",
        category: MemoryCategory | None = None,
        agent: str = "",
        limit: int = 50,
    ) -> list[MemoryEntry]:
        conditions = []
        params: list = []
        if project_id:
            conditions.append("(project_id = ? OR project_id = '')")
            params.append(project_id)
        if category:
            conditions.append("category = ?")
            params.append(category.value)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)

        where = " AND ".join(conditions) if conditions else "1=1"
        cursor = await self._db.execute(
            f"SELECT * FROM memory_entries WHERE {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_entry(r) for r in rows]

    async def count(self, project_id: str = "") -> int:
        if project_id:
            cursor = await self._db.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE project_id = ? OR project_id = ''",
                (project_id,),
            )
        else:
            cursor = await self._db.execute("SELECT COUNT(*) FROM memory_entries")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def replace_all(self, project_id: str, entries: list[MemoryEntry]) -> None:
        await self._db.execute(
            "DELETE FROM memory_entries WHERE project_id = ?", (project_id,),
        )
        await self.append(entries)

    @staticmethod
    def _row_to_entry(row) -> MemoryEntry:
        return MemoryEntry(
            category=MemoryCategory(row["category"]),
            content=row["content"],
            agent=row["agent"],
            scope=ProjectScope(project_id=row["project_id"]),
            cycle_date=row["cycle_date"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


# ── Schedule Repository ────────────────────────────────────────────


class SQLiteScheduleRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get_by_project(self, project_id: str) -> Schedule | None:
        cursor = await self._db.execute(
            "SELECT * FROM schedules WHERE project_id = ?", (project_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_schedule(row)

    async def list_enabled(self) -> list[Schedule]:
        cursor = await self._db.execute(
            "SELECT * FROM schedules WHERE enabled = 1 ORDER BY project_id",
        )
        rows = await cursor.fetchall()
        return [self._row_to_schedule(r) for r in rows]

    async def save(self, schedule: Schedule) -> None:
        if schedule.id:
            await self._db.execute(
                """UPDATE schedules SET cron_expression = ?, enabled = ?,
                   last_run = ?, next_run = ? WHERE id = ?""",
                (
                    str(schedule.cron), int(schedule.enabled),
                    schedule.last_run.isoformat() if schedule.last_run else None,
                    schedule.next_run.isoformat() if schedule.next_run else None,
                    schedule.id,
                ),
            )
        else:
            await self._db.execute(
                """INSERT INTO schedules
                   (project_id, cron_expression, enabled, last_run, next_run, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    schedule.project_id, str(schedule.cron), int(schedule.enabled),
                    schedule.last_run.isoformat() if schedule.last_run else None,
                    schedule.next_run.isoformat() if schedule.next_run else None,
                    _now_iso(),
                ),
            )
        await self._db.commit()

    async def delete(self, schedule_id: int) -> None:
        await self._db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await self._db.commit()

    @staticmethod
    def _row_to_schedule(row) -> Schedule:
        return Schedule(
            id=row["id"],
            project_id=row["project_id"],
            cron=CronExpression(row["cron_expression"]),
            enabled=bool(row["enabled"]),
            last_run=datetime.fromisoformat(row["last_run"]) if row["last_run"] else None,
            next_run=datetime.fromisoformat(row["next_run"]) if row["next_run"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )
