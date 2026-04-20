"""Sprint E M1 — project memory viewer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.queries.list_project_memory import ListProjectMemoryQuery
from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteMemoryStore,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "memory.db"))
    yield conn
    await conn.close()


async def _mk_app(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    memory_store = SQLiteMemoryStore(db)
    app = create_web_app(
        project_repo, cycle_repo, EventBus(), SSEHub(),
        memory_store=memory_store,
    )
    return app, project_repo, memory_store


def _entry(content: str, *, project_id: str = "alpha", category=MemoryCategory.CONVENTIONS,
           agent: str = "dev", cycle_date: str = "2026-04-20",
           created_at: datetime | None = None) -> MemoryEntry:
    return MemoryEntry(
        category=category,
        content=content,
        agent=agent,
        scope=ProjectScope(project_id=project_id),
        cycle_date=cycle_date,
        created_at=created_at or datetime.now(timezone.utc),
    )


async def test_list_project_memory_query_filters_by_category_and_agent(db):
    store = SQLiteMemoryStore(db)
    await store.append([
        _entry("prefer black for formatting", category=MemoryCategory.CONVENTIONS, agent="dev"),
        _entry("missing tests caused regression", category=MemoryCategory.ERRORS, agent="qa"),
        _entry("drop n+1 queries", category=MemoryCategory.IMPROVEMENTS, agent="techlead"),
    ])
    query = ListProjectMemoryQuery(store)
    all_entries = await query.execute("alpha")
    assert len(all_entries) == 3
    conv_only = await query.execute("alpha", category="conventions")
    assert len(conv_only) == 1
    assert conv_only[0].category == "conventions"
    qa_only = await query.execute("alpha", agent="qa")
    assert len(qa_only) == 1
    assert qa_only[0].agent == "qa"


async def test_list_project_memory_query_includes_global_scope(db):
    store = SQLiteMemoryStore(db)
    await store.append([
        _entry("project specific lesson", project_id="alpha"),
        _entry("global cross-project wisdom", project_id=""),
    ])
    query = ListProjectMemoryQuery(store)
    results = await query.execute("alpha")
    assert len(results) == 2
    kinds = {e.is_global for e in results}
    assert kinds == {True, False}


async def test_memory_viewer_route_renders_entries(db):
    app, project_repo, store = await _mk_app(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    await store.append([
        _entry("use black formatter", category=MemoryCategory.CONVENTIONS),
        _entry("avoid n+1 queries", category=MemoryCategory.IMPROVEMENTS),
    ])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/alpha/memory")
    assert r.status_code == 200
    assert 'data-testid="memory-viewer"' in r.text
    assert 'data-testid="memory-list"' in r.text
    assert 'data-testid="memory-search"' in r.text
    assert 'data-testid="memory-pagination"' in r.text
    assert 'use black formatter' in r.text
    assert 'avoid n+1 queries' in r.text
    assert '/static/js/memory-viewer.js' in r.text


async def test_memory_viewer_category_filter_param(db):
    app, project_repo, store = await _mk_app(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    await store.append([
        _entry("convention one", category=MemoryCategory.CONVENTIONS),
        _entry("error pattern", category=MemoryCategory.ERRORS),
    ])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/alpha/memory?category=conventions")
    assert r.status_code == 200
    assert 'convention one' in r.text
    assert 'error pattern' not in r.text


async def test_memory_viewer_empty_state(db):
    app, project_repo, _ = await _mk_app(db)
    await project_repo.save(Project(id="beta", repo=RepoUrl("o/beta")))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/beta/memory")
    assert r.status_code == 200
    assert 'No memory entries yet' in r.text


async def test_memory_viewer_404_when_project_missing(db):
    app, _, _ = await _mk_app(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/ghost/memory")
    assert r.status_code == 404


async def test_project_detail_links_to_memory_viewer(db):
    app, project_repo, _ = await _mk_app(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/projects/alpha")
    assert r.status_code == 200
    assert 'data-testid="project-memory-link"' in r.text
    assert '/projects/alpha/memory' in r.text
