"""A persona is data (phase B, B1).

The owner says who each role is — a name, a description, instructions — for
every project or for one. A project's persona inherits from the instance's,
the instance's from the built-in role. A cycle reads its project's team when
it starts; the words enter every prompt of that role through `load_context`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm import api as api_module
from theswarm.agents.base import _build_persona_preamble, load_context
from theswarm.application.events.bus import EventBus
from theswarm.application.services.agent_settings import AgentSettingsService
from theswarm.application.services.personas import PersonaService
from theswarm.domain.agents.persona import INSTRUCTIONS_MAX, Persona, PersonaError
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.agent_settings_repo import SQLiteAgentSettingsRepository
from theswarm.infrastructure.persistence.persona_repo import SQLitePersonaRepository
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

APP, OTHER = "jrechet/concert-tour-app", "jrechet/espace-client"


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "p.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def service(db):
    models = AgentSettingsService(SQLiteAgentSettingsRepository(db))
    return PersonaService(SQLitePersonaRepository(db), models), models


# ── The record ─────────────────────────────────────────────────────────


def test_a_persona_is_a_role_of_the_table_for_the_instance_or_a_project():
    assert Persona(scope="", key="dev", instructions="Type every function.").empty is False
    assert Persona(scope=APP, key="qa").empty
    for bad in (dict(scope="", key="designer"), dict(scope="not a repo", key="dev"),
                dict(scope="", key="dev", model="gpt"), dict(scope="", key="dev", instructions="x" * (INSTRUCTIONS_MAX + 1))):
        with pytest.raises(PersonaError):
            Persona(**bad)


# ── The team, resolved ─────────────────────────────────────────────────


async def test_a_project_inherits_the_instance_which_inherits_the_role(service):
    personas, _ = service
    assert personas.team(APP)["techlead"].name == "Tech Lead"  # nothing written: as built in

    await personas.save("", "dev", instructions="Type every function.", by="jrechet")
    await personas.save(APP, "dev", name="Aarav", description="Careful with migrations.", by="jrechet")

    on_app, elsewhere = personas.team(APP)["dev"], personas.team(OTHER)["dev"]
    assert (on_app.name, on_app.description, on_app.instructions) == (
        "Aarav", "Careful with migrations.", "Type every function.")
    assert on_app.sources == {"name": "project", "description": "project", "instructions": "instance",
                              "model": "built-in", "effort": "built-in"}
    assert (elsewhere.name, elsewhere.instructions) == ("Developer", "Type every function.")


async def test_the_model_falls_back_on_settings_agents_and_a_project_may_choose_its_own(service):
    personas, models = service
    await models.save_all({"dev": ("sonnet", "high")})
    await personas.refresh()
    assert (personas.team(APP)["dev"].model, personas.team(APP)["dev"].effort) == ("sonnet", "high")

    await personas.save(APP, "dev", model="opus", by="jrechet")  # its effort with it: Claude Code's own
    assert (personas.team(APP)["dev"].model, personas.team(APP)["dev"].effort) == ("opus", "")
    assert personas.team(OTHER)["dev"].model == "sonnet"


async def test_everything_empty_is_no_row(service, db):
    personas, _ = service
    await personas.save(APP, "qa", instructions="Film the mobile width too.")
    await personas.save(APP, "qa")
    assert personas.stored(APP, "qa") is None
    assert await SQLitePersonaRepository(db).list_all() == []


async def test_a_cycle_gets_its_project_s_models_and_words(service):
    personas, models = service
    await models.save_all({"qa": ("haiku", "")})
    await personas.save("", "techlead", instructions="Refuse a PR without tests.")
    await personas.save(APP, "dev", name="Aarav", model="opus", effort="high")

    chosen, words = await personas.for_cycle(APP)
    assert chosen == {"qa": ("haiku", ""), "dev": ("opus", "high")}
    assert words == {
        "techlead": {"name": "Tech Lead", "description": "", "instructions": "Refuse a PR without tests."},
        "dev": {"name": "Aarav", "description": "", "instructions": ""},
    }
    assert (await personas.for_cycle(OTHER))[1].keys() == {"techlead"}


# ── The words reach the prompt ─────────────────────────────────────────


def test_the_preamble_carries_the_owner_s_words():
    text = _build_persona_preamble("dev", None, APP, {
        "name": "Aarav", "description": "Careful with migrations.", "instructions": "Type every function."})
    assert text.startswith("## Persona") and "**Aarav**, the DEV on project" in text
    assert "Careful with migrations." in text
    assert "### Instructions from the owner of this project\n\nType every function." in text
    assert "the form of the answer a prompt asks for stands" in text


def test_without_words_the_preamble_is_what_it_was():
    assert _build_persona_preamble("dev", None, APP) == _build_persona_preamble("dev", None, APP, {})
    assert "Instructions from the owner" not in _build_persona_preamble("dev", None, APP)


async def test_every_agent_s_context_opens_with_its_persona():
    state = {"phase": "review_loop", "github": None, "project_id": APP,
             "personas": {"techlead": {"name": "Tech Lead", "description": "", "instructions": "Refuse a PR without tests."}}}
    context = (await load_context(state))["context"]
    assert "Refuse a PR without tests." in context
    assert "Refuse" not in (await load_context({**state, "phase": "development"}))["context"]  # another role's


def test_the_state_declares_the_key():
    from theswarm.config import AgentState

    assert "personas" in AgentState.__annotations__


# ── The cycle reads its team when it starts ────────────────────────────


async def test_the_api_cycle_hands_the_team_to_the_cycle():
    seen = {}

    async def daily(config, **kw):
        seen["models"], seen["personas"] = dict(config.agent_settings), dict(config.personas)
        return {"cost_usd": 0.0, "prs": [], "date": "2026-11-15"}

    async def for_cycle(repo):
        seen["repo"] = repo
        return {"dev": ("opus", "high")}, {"dev": {"name": "Aarav", "description": "", "instructions": "Type every function."}}

    api_module.set_personas(SimpleNamespace(for_cycle=for_cycle))
    try:
        with patch("theswarm.cycle.run_daily_cycle", new=daily):
            await api_module.run_api_cycle(cycle_id="abc123abc777", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=EventBus())
    finally:
        api_module.set_personas(None)
    assert seen["repo"] == "o/r" and seen["models"] == {"dev": ("opus", "high")}
    assert seen["personas"]["dev"]["instructions"] == "Type every function."


async def test_a_team_that_cannot_be_read_leaves_the_roles_as_built_in():
    seen = {}

    async def daily(config, **kw):
        seen["personas"] = dict(config.personas)
        return {"cost_usd": 0.0, "prs": [], "date": "2026-11-15"}

    async def broken(repo):
        raise RuntimeError("database is locked")

    api_module.set_personas(SimpleNamespace(for_cycle=broken))
    try:
        with patch("theswarm.cycle.run_daily_cycle", new=daily):
            await api_module.run_api_cycle(cycle_id="abc123abc778", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=EventBus())
    finally:
        api_module.set_personas(None)
    assert seen["personas"] == {}


# ── Settings → Agents is the editor ────────────────────────────────────


@pytest.fixture
async def web(db):
    projects = SQLiteProjectRepository(db)
    for repo in (APP, OTHER):
        await projects.save(Project(id=repo.replace("/", "-"), repo=RepoUrl(repo)))
    app = create_web_app(projects, SQLiteCycleRepository(db), EventBus(), SSEHub(), base_path="/swarm", db=db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app


async def test_the_page_edits_every_project_s_personas_and_one_project_s(web):
    client, app = web
    page = (await client.get("/settings/agents", headers={"accept": "text/html"})).text
    assert page.count('data-testid="persona"') == 4 and 'data-testid="team-scopes"' in page  # the cycle's four
    assert 'data-testid="persona-model"' not in page  # the model for every project is set above

    saved = await client.post("/settings/agents/persona", data={
        "team": "", "key": "techlead", "instructions": "Refuse a PR without tests."})
    assert saved.status_code == 303 and "team_saved=techlead" in saved.headers["location"]
    saved = await client.post("/settings/agents/persona", data={
        "team": APP, "key": "dev", "name": "Aarav", "model": "opus", "effort": "high"})
    assert "team=jrechet%2Fconcert-tour-app" in saved.headers["location"]

    team = app.state.personas.team(APP)
    assert team["dev"].name == "Aarav" and team["dev"].model == "opus"
    assert team["techlead"].instructions == "Refuse a PR without tests."

    on_app = (await client.get(f"/settings/agents?team={APP}", headers={"accept": "text/html"})).text
    assert 'value="Aarav"' in on_app and 'data-testid="persona-model"' in on_app
    assert "Inherits the instructions written for every project" in on_app


async def test_a_role_or_a_project_the_page_does_not_have_is_refused(web):
    client, app = web
    assert (await client.post("/settings/agents/persona", data={"team": "", "key": "designer"})).status_code == 400
    assert (await client.post("/settings/agents/persona", data={"team": "", "key": "devops",
                                                              "instructions": "x"})).status_code == 400  # not in the cycle
    assert (await client.post("/settings/agents/persona", data={"team": "o/unknown", "key": "dev",
                                                              "instructions": "x"})).status_code == 400
    too_long = await client.post("/settings/agents/persona", data={"team": "", "key": "dev",
                                                                 "instructions": "x" * (INSTRUCTIONS_MAX + 1)})
    assert too_long.status_code == 400 and app.state.personas.stored("", "dev") is None


async def test_the_theater_names_its_stations_as_the_team_does(web):
    from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker

    client, app = web
    await app.state.personas.save(APP, "dev", name="Aarav")
    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo=APP, issue_number=905))
    tracker.update_status(record.id, CycleStatus.RUNNING)
    try:
        with patch("theswarm.tools.github.GitHubClient") as klass:
            from unittest.mock import AsyncMock

            klass.return_value.get_issue = AsyncMock(return_value={"number": 905, "title": "Change a venue"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            stage = (await client.get(f"/cycles/{record.id}/stage")).text
        assert "Aarav" in stage and "Tech Lead" in stage
    finally:
        tracker._cycles.pop(record.id, None)
