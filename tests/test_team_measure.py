"""A team is measured (phase B, B6): every harness run names the team that
built it, and two teams are compared on the same features — "modular"
without this means "not measured"."""

from __future__ import annotations

from theswarm import evals


def _run(team, passed=True, behaviour="verified", cost=2.0, seconds=1200, outcome=None):
    return {"team": team, "passed": passed, "outcome": outcome or (evals.OUTCOME_BUILT if passed else evals.OUTCOME_FAILED),
            "behaviour": behaviour if passed else "unverified", "cost_usd": cost, "duration_s": seconds}


def test_a_run_before_teams_or_on_an_unedited_team_is_the_built_in_one():
    assert evals.team_name("") == evals.team_name(None) == evals.BUILT_IN_TEAM
    assert evals.team_name("o/app v0 · instance v0") == evals.BUILT_IN_TEAM
    assert evals.team_name("o/app v3 · instance v1") == "o/app v3 · instance v1"


def test_each_team_is_measured_on_what_it_delivered():
    history = [
        _run(""), _run("", cost=4.0, seconds=2400), _run("", passed=False),
        _run("o/app v2 · instance v0", cost=3.0, seconds=900),
        _run("o/app v2 · instance v0", behaviour="broken", cost=5.0, seconds=1500),
        _run("o/app v2 · instance v0", outcome=evals.OUTCOME_INTERRUPTED, passed=False),  # never measured
    ]
    built_in, edited = evals.by_team(history)

    assert built_in == {"team": evals.BUILT_IN_TEAM, "runs": 3, "built": 2, "verified": 2, "broken": 0,
                        "built_rate": 2 / 3, "median_cost_usd": 3.0, "median_duration_s": 1800.0}
    assert edited["team"] == "o/app v2 · instance v0" and edited["runs"] == 2 and edited["built"] == 2
    assert edited["verified"] == 1 and edited["broken"] == 1 and edited["median_cost_usd"] == 4.0
    assert evals.by_team([]) == []


def test_the_cycle_s_result_and_the_harness_record_name_the_team():
    import inspect
    import pathlib

    from theswarm import cycle_graph

    assert '"team": getattr(rt.config, "team_label", "")' in inspect.getsource(cycle_graph.finish)
    root = pathlib.Path(__file__).resolve().parent.parent
    assert 'result["team"] = str(cycle_result.get("team") or "")' in (root / "scripts/cycle_e2e.py").read_text()
    assert '"team": str(result.get("team") or "")' in (root / "scripts/parallel_e2e.py").read_text()


async def test_the_api_and_the_project_page_compare_the_teams(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository, init_db
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.routes import common
    from theswarm.presentation.web.sse import SSEHub

    conn = await init_db(str(tmp_path / "m.db"))
    try:
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(),
                             base_path="/swarm", db=conn)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for record in (_run(""), _run("o/app v2 · instance v0", cost=3.0)):
                await client.post("/api/evals/runs", json={"repo": "o/app", "feature": "x", **record})
            teams = (await client.get("/api/evals/teams?repo=o/app")).json()["teams"]
            assert [t["team"] for t in teams] == [evals.BUILT_IN_TEAM, "o/app v2 · instance v0"]
            assert (await client.get("/api/evals/teams")).json() == {"teams": []}
        trend = await common._evals_trend(app.state, "o/app")
        assert len(trend["by_team"]) == 2 and trend["count"] == 2
    finally:
        await conn.close()
