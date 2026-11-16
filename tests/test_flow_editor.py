"""The flow, drawn (phase B, B4): each flow's steps, the insertion points as
slots, the team's free personas in them — and a persona moved from one point
to another. Only a point takes a drop, so no flow that does not ship can be drawn."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.teams.templates import DRAWINGS, TEMPLATES
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

APP = "jrechet/concert-tour-app"


def test_every_flow_is_drawn_with_its_own_insertion_points_and_keeps_the_review_and_the_merge_gate():
    for flow in TEMPLATES:
        steps = DRAWINGS[flow.key]
        slots = tuple(key for kind, key, _ in steps if kind == "slot")
        assert slots == flow.insertion_points, flow.key
        assert ("role", "techlead", "Review") in steps and ("gate", "merge", "Merge on green CI") in steps
        assert steps.index(("role", "techlead", "Review")) < steps.index(("gate", "merge", "Merge on green CI"))


@pytest.fixture
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "fe.db"))
    projects = SQLiteProjectRepository(conn)
    await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
    app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, app
    await conn.close()


async def test_the_page_draws_the_three_flows_with_the_team_in_them(web):
    client, app = web
    await app.state.personas.save(APP, "dev", name="Aarav")
    await app.state.personas.save_extra("", name="Changelog", prompt="One line.", point="after_qa")
    await app.state.personas.save_extra(APP, name="Security", prompt="No secret.", point="before_merge", effect="block")

    page = (await client.get(f"/settings/agents?team={APP}", headers={"accept": "text/html"})).text
    assert page.count('data-testid="flow"') == 3 and 'data-flow="fix"' in page and 'data-flow="review"' in page
    assert "Aarav" in page  # the roles carry the team's names
    assert 'data-testid="chip-security"' in page and 'data-key="security"' in page  # this team's: it can be moved
    chip = page[page.index('data-testid="chip-changelog"') - 400:page.index('data-testid="chip-changelog"')]
    assert 'draggable="true"' not in chip.split("flow-chip")[-1]  # every project's: shown where it is


async def test_a_persona_is_moved_to_another_point_and_blocks_only_where_it_can(web):
    client, app = web
    await app.state.personas.save_extra(APP, name="Security", prompt="No secret.", point="before_merge", effect="block")

    moved = await client.post("/settings/agents/extra/move", data={"team": APP, "key": "security", "point": "after_qa"})
    assert moved.json() == {"moved": True, "point": "after_qa", "effect": "comment",
                            "note": "It comments there: nothing is left to block."}
    [extra] = app.state.personas.extras_of(APP)
    assert (extra.point, extra.effect, extra.prompt) == ("after_qa", "comment", "No secret.")
    assert len(await app.state.personas.versions(APP)) == 2  # a move is a version of the team

    for bad in ({"team": APP, "key": "security", "point": "before_dev"},   # not a point of any flow
                {"team": APP, "key": "nobody", "point": "after_qa"},
                {"team": "", "key": "security", "point": "after_qa"}):       # another team's persona
        answer = await client.post("/settings/agents/extra/move", data=bad)
        assert answer.status_code == 400 and answer.json()["moved"] is False
