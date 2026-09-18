"""A repo registered from the V2 picker must be allowed for cycles.

`app.state.allowed_repos` is a snapshot taken once at startup from the
environment; registering a project through `/r/{owner}/{name}` writes it to
`project_repo` but never touched that snapshot, so `Play` handed the stale
list to `run_api_cycle` and every freshly-registered repo was refused
(#79/#148). The fix reads the live allowlist as env repos plus every
registered project, straight from `project_repo` — the same source both a
live request and a fresh process after a restart see.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import (
    CycleRequest,
    CycleStatus,
    effective_allowed_repos,
    get_cycle_tracker,
    run_api_cycle,
)
from theswarm.application.commands.create_project import CreateProjectCommand
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture(autouse=True)
def _isolate_cycle_tracker():
    """The tracker is a process singleton — leave it as we found it."""
    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


async def _wait_for(predicate, tries: int = 50) -> None:
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    # The env-configured allowlist deliberately excludes the repo under
    # test, so a pass here can only be explained by registration.
    app.state.allowed_repos = ["jrechet/theswarm"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


async def test_repo_registered_via_picker_is_played_without_refusal(web, monkeypatch):
    client, app = web
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")

    async def quick(*_a, **_kw):
        return {"date": "2026-09-18", "cost_usd": 0.0, "prs": [], "reviews": []}

    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        # Registers jrechet/yakoi, which is absent from app.state.allowed_repos.
        r = await client.get("/r/jrechet/yakoi")
    assert r.status_code == 200

    with patch("theswarm.cycle.run_daily_cycle", side_effect=quick) as mock_run:
        r = await client.post("/r/jrechet/yakoi/issues/2/play")
        assert r.status_code == 303
        cycle_id = r.headers["location"].rsplit("/", 1)[-1]

        tracker = get_cycle_tracker()
        await _wait_for(lambda: tracker.get(cycle_id).status != CycleStatus.QUEUED)

    record = tracker.get(cycle_id)
    assert record.status != CycleStatus.FAILED
    assert record.error is None
    mock_run.assert_called_once()


async def test_registered_repo_is_still_allowed_after_a_restart(tmp_path):
    """A fresh app instance (simulating a restart) reads the same allowlist.

    The allowlist must come from `project_repo`, not an in-memory mutation:
    registering through one `create_web_app()` instance and then building a
    brand-new one against the same database has to see the registration.
    """
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)
    project_repo = SQLiteProjectRepository(conn)

    from theswarm.application.commands.create_project import CreateProjectHandler

    await CreateProjectHandler(project_repo).handle(
        CreateProjectCommand(project_id="yakoi", repo="jrechet/yakoi"),
    )
    await conn.close()

    # A fresh process: new connection, new repo instance, no in-memory state
    # carried over — only the env allowlist plus whatever the DB shows.
    conn2 = await init_db(db_path)
    fresh_project_repo = SQLiteProjectRepository(conn2)

    allowed = await effective_allowed_repos(["jrechet/theswarm"], fresh_project_repo)

    assert "jrechet/yakoi" in allowed
    await conn2.close()


async def test_unknown_repo_is_refused_with_reason_in_the_record(tmp_path, monkeypatch):
    """A repo neither in the environment nor registered is still refused,
    and the reason lands on the tracker record."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    conn = await init_db(str(tmp_path / "test.db"))
    project_repo = SQLiteProjectRepository(conn)

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/never-registered"))

    with patch("theswarm.cycle.run_daily_cycle") as mock_run:
        await run_api_cycle(
            record.id, "jrechet/never-registered", "", "",
            ["jrechet/theswarm"], project_repo=project_repo,
        )

    mock_run.assert_not_called()
    final = tracker.get(record.id)
    assert final.status == CycleStatus.FAILED
    assert final.error is not None
    assert "jrechet/never-registered" in final.error
    assert "not in allowed list" in final.error
    await conn.close()
