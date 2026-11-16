"""A team an agent proposes (phase B, B5, second half): kept for the owner,
applied to nothing until they accept — the model of the DevOps proposals."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tests.presentation.test_mcp_server import APP, _call
from theswarm.application.events.bus import EventBus
from theswarm.application.services.team_yaml import TeamYamlError
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

FILE = "format: 1\npersonas:\n  dev:\n    instructions: Type every function.\n"


@pytest.fixture
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "pr.db"))
    projects = SQLiteProjectRepository(conn)
    await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
    app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


async def test_a_proposal_changes_nothing_until_the_owner_accepts(web):
    client, app = web
    await app.state.personas.save(APP, "qa", instructions="Film the phone width too.")

    wrong, answer = await _call(client, "propose_team", {"project": APP, "yaml": FILE, "why": "The Dev left functions untyped."})
    assert not wrong and answer["status"] == "waiting for the owner" and answer["where"].endswith("#proposals")
    assert app.state.personas.stored(APP, "dev") is None  # nothing applied

    page = (await client.get(f"/settings/agents?team={APP}", headers={"accept": "text/html"})).text
    assert 'data-testid="team-proposal"' in page and "The Dev left functions untyped." in page
    assert "Type every function." in page

    done = await client.post(f"/settings/agents/proposals/{answer['proposal']}/accept")
    assert done.status_code == 303 and "team_saved=import" in done.headers["location"]
    assert app.state.personas.stored(APP, "dev").instructions == "Type every function."
    assert app.state.personas.stored(APP, "qa") is None  # the file replaces the team, as an import does
    assert await app.state.personas.open_proposals(APP) == []
    assert (await client.post(f"/settings/agents/proposals/{answer['proposal']}/accept")).status_code == 409


async def test_a_refusal_stands_and_changes_nothing(web):
    client, app = web
    _, answer = await _call(client, "propose_team", {"project": APP, "yaml": FILE})
    done = await client.post(f"/settings/agents/proposals/{answer['proposal']}/refuse")
    assert done.status_code == 303 and "team_saved=refused" in done.headers["location"]
    assert app.state.personas.stored(APP, "dev") is None and await app.state.personas.open_proposals(APP) == []
    assert (await client.post(f"/settings/agents/proposals/{answer['proposal']}/shrug")).status_code == 400


async def test_a_wrong_file_is_not_proposed_and_an_agent_cannot_bury_the_owner(web):
    client, app = web
    wrong, said = await _call(client, "propose_team", {"project": APP, "yaml": "format: 1\npersonas:\n  dev: {model: gpt}"})
    assert wrong and said.startswith("Not proposed:") and await app.state.personas.open_proposals(APP) == []

    for _ in range(3):
        await app.state.personas.propose(APP, FILE)
    with pytest.raises(TeamYamlError, match="already wait"):
        await app.state.personas.propose(APP, FILE)
    assert await app.state.personas.open_proposals("") == []  # another team's line is its own
