"""Tests for infrastructure/persistence/sqlite_repos.py."""

from __future__ import annotations

import pytest

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import Budget, CycleId, CycleStatus, PhaseStatus
from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import Framework, RepoUrl, TicketSourceType
from theswarm.domain.scheduling.entities import Schedule
from theswarm.domain.scheduling.value_objects import CronExpression
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteMemoryStore,
    SQLiteProjectRepository,
    SQLiteScheduleRepository,
    init_db,
)

from datetime import datetime, timezone


@pytest.fixture()
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)
    yield conn
    await conn.close()


# ── Project Repository ────────────────────────────────────────────


class TestSQLiteProjectRepository:
    async def test_save_and_get(self, db):
        repo = SQLiteProjectRepository(db)
        p = Project(
            id="my-app",
            repo=RepoUrl("owner/my-app"),
            framework=Framework.FASTAPI,
            ticket_source=TicketSourceType.JIRA,
            team_channel="dev-team",
        )
        await repo.save(p)

        loaded = await repo.get("my-app")
        assert loaded is not None
        assert loaded.id == "my-app"
        assert str(loaded.repo) == "owner/my-app"
        assert loaded.framework == Framework.FASTAPI
        assert loaded.ticket_source == TicketSourceType.JIRA
        assert loaded.team_channel == "dev-team"

    async def test_get_nonexistent(self, db):
        repo = SQLiteProjectRepository(db)
        assert await repo.get("nope") is None

    async def test_list_all(self, db):
        repo = SQLiteProjectRepository(db)
        await repo.save(Project(id="a", repo=RepoUrl("o/a")))
        await repo.save(Project(id="b", repo=RepoUrl("o/b")))

        projects = await repo.list_all()
        assert len(projects) == 2
        assert projects[0].id == "a"
        assert projects[1].id == "b"

    async def test_delete(self, db):
        repo = SQLiteProjectRepository(db)
        await repo.save(Project(id="x", repo=RepoUrl("o/x")))
        await repo.delete("x")
        assert await repo.get("x") is None

    async def test_upsert(self, db):
        repo = SQLiteProjectRepository(db)
        p = Project(id="a", repo=RepoUrl("o/a"), framework=Framework.DJANGO)
        await repo.save(p)

        p2 = Project(id="a", repo=RepoUrl("o/a"), framework=Framework.FLASK)
        await repo.save(p2)

        loaded = await repo.get("a")
        assert loaded.framework == Framework.FLASK

    async def test_config_roundtrip(self, db):
        repo = SQLiteProjectRepository(db)
        p = Project(
            id="x", repo=RepoUrl("o/x"),
            config=ProjectConfig(max_daily_stories=5, token_budget_dev=500_000),
        )
        await repo.save(p)

        loaded = await repo.get("x")
        assert loaded.config.max_daily_stories == 5
        assert loaded.config.token_budget_dev == 500_000


# ── Cycle Repository ──────────────────────────────────────────────


class TestSQLiteCycleRepository:
    async def test_save_and_get(self, db):
        repo = SQLiteCycleRepository(db)
        now = datetime.now(timezone.utc)
        phase = PhaseExecution(
            phase="morning", agent="po", started_at=now,
            status=PhaseStatus.COMPLETED, completed_at=now,
            tokens_used=5000, cost_usd=0.10, summary="Selected stories",
        )
        cycle = Cycle(
            id=CycleId("c1"), project_id="p1",
            status=CycleStatus.COMPLETED,
            triggered_by="user:jre",
            started_at=now, completed_at=now,
            phases=(phase,),
            budgets=(Budget("po", 300000, 5000),),
            total_cost_usd=0.10,
            prs_opened=(42,), prs_merged=(42,),
        )
        await repo.save(cycle)

        loaded = await repo.get(CycleId("c1"))
        assert loaded is not None
        assert loaded.status == CycleStatus.COMPLETED
        assert loaded.triggered_by == "user:jre"
        assert len(loaded.phases) == 1
        assert loaded.phases[0].summary == "Selected stories"
        assert loaded.total_cost_usd == pytest.approx(0.10)
        assert 42 in loaded.prs_opened
        assert 42 in loaded.prs_merged
        assert len(loaded.budgets) == 1

    async def test_get_nonexistent(self, db):
        repo = SQLiteCycleRepository(db)
        assert await repo.get(CycleId("nope")) is None

    async def test_list_by_project(self, db):
        repo = SQLiteCycleRepository(db)
        now = datetime.now(timezone.utc)

        for i in range(5):
            c = Cycle(
                id=CycleId(f"c{i}"), project_id="p1",
                status=CycleStatus.COMPLETED, started_at=now,
            )
            await repo.save(c)

        # Different project
        await repo.save(Cycle(id=CycleId("other"), project_id="p2", started_at=now))

        result = await repo.list_by_project("p1", limit=3)
        assert len(result) == 3
        assert all(c.project_id == "p1" for c in result)


# ── Memory Store ──────────────────────────────────────────────────


class TestSQLiteMemoryStore:
    async def test_append_and_load(self, db):
        store = SQLiteMemoryStore(db)
        entries = [
            MemoryEntry(
                category=MemoryCategory.STACK,
                content="Uses FastAPI", agent="dev",
                scope=ProjectScope("p1"),
            ),
            MemoryEntry(
                category=MemoryCategory.ERRORS,
                content="Don't use print", agent="qa",
                scope=ProjectScope("p1"),
            ),
        ]
        await store.append(entries)

        loaded = await store.load("p1")
        assert len(loaded) == 2
        assert loaded[0].content == "Uses FastAPI"

    async def test_load_includes_global(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="global", agent="dev"),
            MemoryEntry(
                category=MemoryCategory.STACK, content="project",
                agent="dev", scope=ProjectScope("p1"),
            ),
        ])

        loaded = await store.load("p1")
        assert len(loaded) == 2

    async def test_load_all(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="a", agent="dev"),
            MemoryEntry(
                category=MemoryCategory.STACK, content="b",
                agent="dev", scope=ProjectScope("p1"),
            ),
        ])
        loaded = await store.load()
        assert len(loaded) == 2

    async def test_query_by_category(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="a", agent="dev"),
            MemoryEntry(category=MemoryCategory.ERRORS, content="b", agent="qa"),
        ])

        result = await store.query(category=MemoryCategory.STACK)
        assert len(result) == 1
        assert result[0].content == "a"

    async def test_query_by_agent(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="a", agent="dev"),
            MemoryEntry(category=MemoryCategory.STACK, content="b", agent="qa"),
        ])

        result = await store.query(agent="qa")
        assert len(result) == 1

    async def test_count(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="a", agent="dev", scope=ProjectScope("p1")),
            MemoryEntry(category=MemoryCategory.STACK, content="b", agent="dev"),
        ])
        assert await store.count("p1") == 2  # includes global
        assert await store.count() == 2

    async def test_replace_all(self, db):
        store = SQLiteMemoryStore(db)
        await store.append([
            MemoryEntry(category=MemoryCategory.STACK, content="old", agent="dev", scope=ProjectScope("p1")),
        ])

        new_entries = [
            MemoryEntry(category=MemoryCategory.CONVENTIONS, content="new", agent="dev", scope=ProjectScope("p1")),
        ]
        await store.replace_all("p1", new_entries)

        loaded = await store.load("p1")
        assert len(loaded) == 1
        assert loaded[0].content == "new"


# ── Schedule Repository ───────────────────────────────────────────


class TestSQLiteScheduleRepository:
    async def test_save_and_get(self, db):
        repo = SQLiteScheduleRepository(db)
        s = Schedule(project_id="p1", cron=CronExpression("0 8 * * 1-5"))
        await repo.save(s)

        loaded = await repo.get_by_project("p1")
        assert loaded is not None
        assert str(loaded.cron) == "0 8 * * 1-5"
        assert loaded.enabled is True

    async def test_get_nonexistent(self, db):
        repo = SQLiteScheduleRepository(db)
        assert await repo.get_by_project("nope") is None

    async def test_list_enabled(self, db):
        repo = SQLiteScheduleRepository(db)
        await repo.save(Schedule(project_id="p1", cron=CronExpression("0 8 * * *")))
        await repo.save(Schedule(project_id="p2", cron=CronExpression("0 9 * * *"), enabled=False))

        enabled = await repo.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].project_id == "p1"

    async def test_update(self, db):
        repo = SQLiteScheduleRepository(db)
        s = Schedule(project_id="p1", cron=CronExpression("0 8 * * *"))
        await repo.save(s)

        loaded = await repo.get_by_project("p1")
        disabled = loaded.disable()
        await repo.save(disabled)

        reloaded = await repo.get_by_project("p1")
        assert reloaded.enabled is False

    async def test_delete(self, db):
        repo = SQLiteScheduleRepository(db)
        await repo.save(Schedule(project_id="p1", cron=CronExpression("0 8 * * *")))
        loaded = await repo.get_by_project("p1")
        await repo.delete(loaded.id)
        assert await repo.get_by_project("p1") is None
