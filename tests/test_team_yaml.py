"""A team is a file, it is versioned, and a cycle keeps the one it started with (phase B, B2)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.services import team_yaml
from theswarm.application.services.agent_settings import AgentSettingsService
from theswarm.application.services.personas import PersonaService
from theswarm.application.services.team_yaml import TeamYamlError
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

APP = "jrechet/concert-tour-app"


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def personas(db):
    return PersonaService(SQLitePersonaRepository(db), AgentSettingsService(SQLiteAgentSettingsRepository(db)))


# ── The file ───────────────────────────────────────────────────────────


async def test_export_then_import_is_the_same_team(personas):
    await personas.save(APP, "dev", name="Aarav", instructions="Type every function.\nNo print().", model="opus", effort="high")
    await personas.save(APP, "techlead", description="Guards main.")
    text = personas.export_yaml(APP)

    assert "team: jrechet/concert-tour-app" in text and "format: 1" in text and "template: feature" in text
    assert "instructions: |" in text  # several lines read as a block
    assert "qa" not in text  # only what was written

    await personas.save(APP, "dev")  # wiped
    await personas.import_yaml(APP, text, by="jrechet")
    assert personas.export_yaml(APP) == text
    assert personas.team(APP)["dev"].instructions == "Type every function.\nNo print()."


async def test_an_import_replaces_the_scope_and_only_it(personas):
    await personas.save("", "qa", instructions="Film the phone width too.")
    await personas.save(APP, "dev", name="Aarav")
    await personas.import_yaml(APP, "format: 1\npersonas:\n  techlead:\n    instructions: Refuse a PR without tests.\n")

    assert personas.stored(APP, "dev") is None and personas.stored(APP, "techlead").instructions.startswith("Refuse")
    assert personas.stored("", "qa") is not None  # every project's team is another file


@pytest.mark.parametrize("text, said", [
    ("- a list", "is a mapping"),
    ("format: 2\npersonas: {}", "format: 1"),
    ("format: 1\nteam: o/other\npersonas: {}", "the team of 'o/other'"),
    ("format: 1\ntemplate: bugfix\npersonas: {}", "only flow yet"),
    ("format: 1\npersonas:\n  designer: {name: x}", "not a role of the cycle"),
    ("format: 1\npersonas:\n  dev: {tools: [Bash]}", "tools is not a field"),
    ("format: 1\npersonas:\n  dev: {model: gpt}", "not one of"),
    ("format: 1\npersonas:\n  dev: {effort: high}", "goes with a model"),
    ("format: 1\npersonas: [", "Not valid YAML"),
])
async def test_a_file_that_is_wrong_says_what_and_changes_nothing(personas, text, said):
    await personas.save(APP, "dev", name="Aarav")
    with pytest.raises(TeamYamlError, match=said):
        await personas.import_yaml(APP, text)
    assert personas.stored(APP, "dev").name == "Aarav"


def test_the_instance_s_file_carries_no_model():
    with pytest.raises(TeamYamlError, match="Settings → Agents"):
        team_yaml.load("format: 1\npersonas:\n  dev: {model: opus}", "")


# ── Versions ───────────────────────────────────────────────────────────


async def test_every_change_is_a_version_and_the_same_file_is_not_a_new_one(personas):
    await personas.save(APP, "dev", name="Aarav", by="jrechet")
    await personas.save(APP, "dev", name="Aarav", by="jrechet")  # nothing changed
    await personas.save(APP, "dev", name="Aarav", instructions="Type every function.", by="jrechet")

    versions = await personas.versions(APP)
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["created_by"] == "jrechet"
    assert "Type every function." in versions[0]["body"] and "Type" not in versions[1]["body"]
    assert await personas.versions("") == []


# ── A cycle keeps the team it started with ─────────────────────────────


async def test_a_continuation_runs_the_team_its_thread_started_with(personas):
    await personas.save(APP, "dev", instructions="Type every function.")
    models, words, label = await personas.for_thread("thread-1", APP)
    assert words["dev"]["instructions"] == "Type every function." and label == f"{APP} v1 · instance v0"

    await personas.save(APP, "dev", instructions="Never type anything.", model="opus")  # edited while it runs

    again = await personas.for_thread("thread-1", APP)  # the resume after a deploy or a pause
    assert again == (models, words, label) and again[0] == {}
    fresh = await personas.for_thread("thread-2", APP)  # the next cycle
    assert fresh[1]["dev"]["instructions"] == "Never type anything." and fresh[0] == {"dev": ("opus", "")}
    assert fresh[2] == f"{APP} v2 · instance v0"


async def test_the_api_cycle_asks_for_its_thread_s_team():
    from types import SimpleNamespace
    from unittest.mock import patch

    from theswarm import api as api_module

    asked = {}

    async def for_thread(thread, repo):
        asked["thread"], asked["repo"] = thread, repo
        return {}, {"dev": {"name": "Aarav", "description": "", "instructions": ""}}, "o/r v1 · instance v0"

    async def daily(config, **kw):
        asked["personas"] = dict(config.personas)
        return {"cost_usd": 0.0, "prs": [], "date": "2026-11-15"}

    api_module.set_personas(SimpleNamespace(for_thread=for_thread))
    try:
        with patch("theswarm.cycle.run_daily_cycle", new=daily):
            await api_module.run_api_cycle(cycle_id="abc123abc901", repo="o/r", description="Resume", callback_url="",
                                           allowed_repos=[], event_bus=EventBus(), resume_cycle_id="origin000001")
    finally:
        api_module.set_personas(None)
    assert asked["thread"] == "origin000001" and asked["personas"]["dev"]["name"] == "Aarav"


# ── The page ───────────────────────────────────────────────────────────


@pytest.fixture
async def web(db):
    projects = SQLiteProjectRepository(db)
    await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
    app = create_web_app(projects, SQLiteCycleRepository(db), EventBus(), SSEHub(), base_path="/swarm", db=db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app


async def test_the_page_exports_and_imports_the_team(web):
    client, app = web
    await app.state.personas.save(APP, "dev", name="Aarav")

    file = await client.get(f"/settings/agents/team.yaml?team={APP}")
    assert file.status_code == 200 and file.headers["content-type"].startswith("text/yaml")
    assert "name: Aarav" in file.text
    assert (await client.get("/settings/agents/team.yaml?team=o/unknown")).status_code == 404

    done = await client.post("/settings/agents/team/import", data={
        "team": APP, "yaml": "format: 1\npersonas:\n  qa:\n    instructions: Film the phone width too.\n"})
    assert done.status_code == 303 and "team_saved=import" in done.headers["location"]
    assert app.state.personas.stored(APP, "dev") is None
    page = (await client.get(f"/settings/agents?team={APP}&team_saved=import", headers={"accept": "text/html"})).text
    assert 'data-testid="team-file"' in page and "Film the phone width too." in page and "version 2" in page

    bad = await client.post("/settings/agents/team/import", data={"team": APP, "yaml": "format: 9"})
    assert bad.status_code == 400 and "was not imported" in bad.text
    assert app.state.personas.stored(APP, "qa") is not None  # nothing changed
