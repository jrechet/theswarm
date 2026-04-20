"""Sprint F M3 — memory compaction service tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from theswarm.application.services.memory_compaction import (
    MemoryCompactionService,
    run_compaction_loop,
)
from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteMemoryStore,
    SQLiteProjectRepository,
    init_db,
)


FIXED_NOW = datetime(2026, 5, 1, 3, 0, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return FIXED_NOW


def _entry(
    content: str, *, project_id: str = "alpha", agent: str = "dev",
    category: MemoryCategory = MemoryCategory.CONVENTIONS,
    created_at: datetime | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        category=category,
        content=content,
        agent=agent,
        scope=ProjectScope(project_id=project_id),
        cycle_date=(created_at or FIXED_NOW).date().isoformat(),
        created_at=created_at or FIXED_NOW,
    )


@pytest.fixture
async def store(tmp_path):
    conn = await init_db(str(tmp_path / "compact.db"))
    yield SQLiteMemoryStore(conn), conn
    await conn.close()


async def test_dedup_keeps_earliest(store):
    s, _ = store
    old = _entry("same lesson", created_at=FIXED_NOW - timedelta(days=5))
    new = _entry("same lesson", created_at=FIXED_NOW - timedelta(days=1))
    await s.append([old, new, _entry("different", created_at=FIXED_NOW)])

    svc = MemoryCompactionService(s, max_entries_per_project=100, clock=_clock)
    result = await svc.compact("alpha")

    assert result.before == 3
    assert result.deduped == 1
    assert result.after == 2
    remaining = await s.query(project_id="alpha", limit=100)
    assert {e.content for e in remaining} == {"same lesson", "different"}


async def test_dedup_noop_when_no_duplicates(store):
    s, _ = store
    await s.append([_entry("a"), _entry("b"), _entry("c")])

    svc = MemoryCompactionService(s, clock=_clock)
    result = await svc.compact("alpha")
    assert result.deduped == 0
    assert result.trimmed == 0
    assert result.after == 3


async def test_trim_to_max_entries_adds_marker(store):
    s, _ = store
    # 10 entries spread across 10 days
    base = FIXED_NOW - timedelta(days=10)
    for i in range(10):
        await s.append([_entry(f"lesson-{i}", created_at=base + timedelta(days=i))])

    svc = MemoryCompactionService(
        s, max_entries_per_project=5,
        max_bytes_per_project=10_000_000,  # effectively unlimited bytes
        clock=_clock,
    )
    result = await svc.compact("alpha")

    assert result.trimmed >= 5  # trimmed enough oldest to fit the cap
    remaining = await s.query(project_id="alpha", limit=100)
    contents = [e.content for e in remaining]
    assert any(c.startswith("[compaction]") for c in contents)
    # Youngest entries should survive
    assert "lesson-9" in contents
    assert "lesson-8" in contents


async def test_trim_to_byte_budget(store):
    s, _ = store
    big_content = "x" * 5_000
    base = FIXED_NOW - timedelta(days=30)
    for i in range(30):
        await s.append([_entry(big_content, agent=f"agent-{i}", created_at=base + timedelta(days=i))])

    svc = MemoryCompactionService(
        s, max_bytes_per_project=30_000, max_entries_per_project=10_000, clock=_clock,
    )
    result = await svc.compact("alpha")
    assert result.trimmed > 0
    remaining = await s.query(project_id="alpha", limit=100)
    # Total bytes should be under budget (with some slack for the marker)
    total = sum(len(e.content.encode()) for e in remaining)
    assert total < 30_000 * 2  # generous ceiling; marker is tiny


async def test_no_changes_under_budget(store):
    s, _ = store
    await s.append([_entry(f"note-{i}") for i in range(5)])

    svc = MemoryCompactionService(
        s, max_bytes_per_project=10_000_000, max_entries_per_project=100, clock=_clock,
    )
    result = await svc.compact("alpha")
    assert result.deduped == 0
    assert result.trimmed == 0
    assert result.before == result.after == 5


async def test_only_touches_requested_project(store):
    s, _ = store
    await s.append([
        _entry("dup", project_id="alpha"),
        _entry("dup", project_id="alpha"),
        _entry("dup", project_id="beta"),
        _entry("dup", project_id="beta"),
    ])

    svc = MemoryCompactionService(s, clock=_clock)
    result = await svc.compact("alpha")

    alpha = await s.query(project_id="alpha", limit=100)
    beta = await s.query(project_id="beta", limit=100)
    alpha_in_project = [e for e in alpha if e.scope.project_id == "alpha"]
    beta_in_project = [e for e in beta if e.scope.project_id == "beta"]
    assert len(alpha_in_project) == 1
    assert len(beta_in_project) == 2  # untouched
    assert result.project_id == "alpha"


async def test_run_all_iterates_projects(store, tmp_path):
    s, conn = store
    project_repo = SQLiteProjectRepository(conn)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/a")))
    await project_repo.save(Project(id="beta", repo=RepoUrl("o/b")))

    await s.append([
        _entry("shared", project_id="alpha"),
        _entry("shared", project_id="alpha"),
        _entry("once", project_id="beta"),
    ])

    svc = MemoryCompactionService(s, project_repo, clock=_clock)
    results = await svc.run_all()
    by_project = {r.project_id: r for r in results}
    assert by_project["alpha"].deduped == 1
    assert by_project["beta"].deduped == 0


async def test_run_all_explicit_list_skips_project_repo(store):
    s, _ = store
    await s.append([_entry("a", project_id="alpha")])
    svc = MemoryCompactionService(s, project_repo=None, clock=_clock)
    results = await svc.run_all(project_ids=["alpha"])
    assert len(results) == 1


async def test_run_all_empty_when_no_project_repo(store):
    s, _ = store
    svc = MemoryCompactionService(s, project_repo=None, clock=_clock)
    assert await svc.run_all() == []


async def test_compact_does_not_touch_global_entries(store):
    s, _ = store
    await s.append([
        _entry("project lesson", project_id="alpha"),
        _entry("global lesson", project_id=""),
    ])
    svc = MemoryCompactionService(s, clock=_clock)
    result = await svc.compact("alpha")
    assert result.before == 1  # only alpha's own entries counted
    # Global entry still there
    remaining = await s.query(project_id="alpha", limit=100)
    assert any(e.content == "global lesson" for e in remaining)


async def test_loop_cancellable():
    class _SpyService:
        def __init__(self):
            self.calls = 0

        async def run_all(self):
            self.calls += 1
            return []

    spy = _SpyService()
    task = asyncio.create_task(
        run_compaction_loop(spy, interval_seconds=0.01, initial_delay_seconds=0.0)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert spy.calls >= 1
