"""Settings → Cycles: how many cycles at once, in all and per project — the
owner's page (2026-10-13)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.cycle_gate import max_concurrent_cycles, repo_max_cycles, set_cycle_limits
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

HTML = {"accept": "text/html"}


@pytest.fixture()
async def web(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_MAX_CONCURRENT_CYCLES", "2")
    conn = await init_db(str(tmp_path / "test.db"))
    projects = SQLiteProjectRepository(conn)
    for repo in ("jrechet/concert-tour-app", "jrechet/espace-client"):
        await projects.save(Project(id=repo.replace("/", "-"), repo=RepoUrl(repo)))
    app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    set_cycle_limits(None)
    await conn.close()


async def test_the_page_shows_the_numbers_in_all_and_per_project(web):
    client, _ = web
    r = await client.get("/settings/cycles", headers=HTML)
    assert r.status_code == 200
    assert 'data-testid="in-all"' in r.text and 'value="2"' in r.text
    assert r.text.count('data-testid="cycles-project"') == 2
    assert "jrechet/concert-tour-app" in r.text


async def test_saving_applies_at_once(web):
    client, _ = web
    r = await client.post("/settings/cycles", data={
        "in-all": "3", "repo:jrechet/concert-tour-app": "2", "repo:jrechet/espace-client": "1",
    })
    assert r.status_code == 303 and r.headers["location"].endswith("/settings/cycles?saved=1")
    assert max_concurrent_cycles() == 3
    assert repo_max_cycles("jrechet/concert-tour-app") == 2 and repo_max_cycles("jrechet/espace-client") == 1

    again = await client.get("/settings/cycles?saved=1", headers=HTML)
    assert 'data-testid="cycles-saved"' in again.text and 'value="3"' in again.text


async def test_a_number_out_of_bounds_is_refused_and_nothing_changes(web):
    client, _ = web
    r = await client.post("/settings/cycles", data={"in-all": "40", "repo:jrechet/concert-tour-app": "2"})
    assert r.status_code == 400 and 'data-testid="cycles-error"' in r.text
    assert max_concurrent_cycles() == 2 and repo_max_cycles("jrechet/concert-tour-app") == 1


async def test_the_instances_default_leaves_no_row(web):
    client, app = web
    await client.post("/settings/cycles", data={"in-all": "2", "repo:jrechet/concert-tour-app": "1"})
    assert await app.state.cycle_limits._repo.all() == {}


async def test_a_member_is_refused(web, monkeypatch):
    client, _ = web
    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    r = await client.get("/settings/cycles", headers=HTML, follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)
