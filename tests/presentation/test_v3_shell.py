"""V3, M1 — the design system and the shell (docs/plans/2026-10-v3-one-product.md).

One rail on every page: home, the customers and their projects (Internal
until M2), the project the page is about, Claude's health, who is signed
in. The pages never pass it: `ShellMiddleware` builds it once per HTML
request and the template engine hands it to every template as `shell`.
The home is V3: Now, To review, the projects. The sign-in page wears the
same tokens. The V2 pages render inside the shell until M3/M4 replace them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web import shell as shell_mod
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "theswarm" / "presentation" / "web"
REPO = "jrechet/concert-tour-app"



async def _v3(client, path, **kw):
    """A V2 address registers the project and redirects (303, under the base
    path); the page itself is read at its V3 address inside Internal."""
    await client.get(path.split("?")[0], **kw)
    return await client.get(path.replace("/r/jrechet/", "/c/internal/p/"), **kw)

@pytest.fixture(autouse=True)
def _isolate_tracker():
    from theswarm.api import get_cycle_tracker

    tracker = get_cycle_tracker()
    before = dict(tracker._cycles)
    tracker._cycles.clear()
    yield tracker
    tracker._cycles.clear()
    tracker._cycles.update(before)


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    if getattr(app.state, "report_repo", None) is None:
        app.state.report_repo = SQLiteReportRepository(conn)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


async def _register(app, full_name: str = REPO) -> None:
    await app.state.project_repo.save(Project(id=full_name.replace("/", "-"), repo=RepoUrl(full_name)))


def _running(tracker, repo: str = REPO, cycle_id: str = "abc123abc123", issue: int | None = 85):
    from theswarm.api import CycleRecord, CycleStatus

    record = CycleRecord(
        id=cycle_id, repo=repo, description="Harden input validation and sanitization",
        callback_url="", issue_number=issue, status=CycleStatus.RUNNING,
        created_at="2026-10-06T11:19:00+00:00", started_at="2026-10-06T11:19:30+00:00",
    )
    tracker._cycles[cycle_id] = record
    return record


def _report(rid: str = "rep-1", *, when: datetime | None = None, failed: int = 0) -> DemoReport:
    gates = [QualityGate(name="unit_tests", status=QualityStatus.PASS, detail="312 passed")]
    gates += [QualityGate(name=f"gate{i}", status=QualityStatus.FAIL) for i in range(failed)]
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id=REPO,
        created_at=when or datetime.now(timezone.utc),
        summary=ReportSummary(stories_completed=3, stories_total=3, prs_merged=2, cost_usd=2.14),
        quality_gates=tuple(gates),
    )


async def _home(client):
    """The home with GitHub stubbed out: no App, no repositories, OAuth ready."""
    with patch("theswarm.presentation.web.routes.common.github_app") as gh:
        gh.load_credentials = AsyncMock(return_value=None)
        gh.list_user_repositories = AsyncMock(return_value=[])
        gh.oauth_client = AsyncMock(return_value=object())
        return await client.get("/", headers={"accept": "text/html"})


HTML = {"accept": "text/html"}


# ── The shell on every page ──────────────────────────────────────────


class TestTheShell:
    async def test_the_home_wears_the_rail_and_the_v3_stylesheet(self, web):
        client, app = web
        r = await _home(client)
        assert r.status_code == 200
        assert 'data-testid="rail"' in r.text
        assert "/swarm/static/v3/app.css" in r.text
        assert "Legacy" not in r.text  # the V1 link is gone from the shell
        assert 'data-theme-toggle' in r.text and "swarm-theme" in r.text

    async def test_the_rail_lists_registered_projects_under_internal(self, web):
        client, app = web
        await _register(app)
        r = await _home(client)
        assert 'data-testid="rail-customers"' in r.text and ">Internal<" in r.text
        assert 'href="/swarm/r/jrechet/concert-tour-app"' in r.text
        assert 'data-testid="rail-project" data-running="false"' in r.text

    async def test_a_running_project_gets_the_live_dot(self, web, _isolate_tracker):
        client, app = web
        await _register(app)
        _running(_isolate_tracker)
        r = await _home(client)
        assert 'data-testid="rail-project" data-running="true"' in r.text

    async def test_a_v2_page_renders_inside_the_shell(self, web):
        """The repo page keeps its V2 markup — board, running banner — but
        wears the V3 rail and marks its project active."""
        client, app = web
        await _register(app)
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issues = AsyncMock(return_value=[])
            r = await _v3(client, f"/r/{REPO}", headers=HTML)
        assert r.status_code == 200
        assert 'data-testid="rail"' in r.text
        assert 'aria-current="page"' not in r.text.split('data-testid="rail-customers"')[0]  # home is not active
        assert "bg-raised text-ink font-medium" in r.text.split('data-testid="rail-project"')[1][:400]

    async def test_claude_health_sits_in_the_rail(self, web):
        from theswarm.tools import quota_wall

        client, app = web
        r = await _home(client)
        assert 'data-testid="claude-chip" data-status="ok"' in r.text
        quota_wall.raise_wall("You've hit your session limit · resets in 30 minutes")
        try:
            r = await _home(client)
            assert 'data-status="quota_wall"' in r.text and "quota wall" in r.text
        finally:
            quota_wall.clear()

    async def test_the_signed_in_owner_is_named(self, web):
        from theswarm.presentation.web.auth import SESSION_COOKIE, mint_session

        client, app = web
        client.cookies.set(SESSION_COOKIE, mint_session("jrechet"))
        r = await _home(client)
        assert 'data-testid="actor">jrechet<' in r.text
        assert 'action="/swarm/logout"' in r.text

    async def test_a_failing_project_query_leaves_an_empty_rail_not_an_error(self):
        from types import SimpleNamespace

        state = SimpleNamespace(list_projects_query=SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down"))))
        built = await shell_mod.build_shell(state, {}, "/swarm/", "/swarm")
        assert built["customers"] == [] and built["active"] == "home"
        assert built["claude"]["status"] == "ok"

    async def test_api_and_static_answers_skip_the_shell(self, web):
        """JSON callers never pay for the rail (one DB query per HTML request)."""
        client, app = web
        app.state.list_projects_query.execute = AsyncMock(side_effect=AssertionError("must not be called"))
        r = await client.get("/api/cycles", headers={"accept": "application/json"})
        assert r.status_code in (200, 404)
        r = await client.get("/health")
        assert r.status_code == 200


# ── The home: Now, To review, the projects ───────────────────────────


class TestTheHome:
    async def test_now_lists_the_running_cycle(self, web, _isolate_tracker):
        client, app = web
        _running(_isolate_tracker)
        r = await _home(client)
        assert 'data-testid="now-cycle"' in r.text
        assert 'href="/swarm/cycles/abc123abc123"' in r.text
        assert "#85" in r.text and "Harden input validation" in r.text
        assert "since 11:19 UTC" in r.text

    async def test_now_is_honest_when_nothing_runs(self, web):
        client, app = web
        r = await _home(client)
        assert 'data-testid="now-empty"' in r.text and 'data-testid="now-cycle"' not in r.text

    async def test_to_review_lists_the_latest_demos_with_their_gates(self, web):
        client, app = web
        await app.state.report_repo.save(_report("rep-1"))
        await app.state.report_repo.save(_report("rep-2", when=datetime.now(timezone.utc) - timedelta(days=1), failed=1))
        r = await _home(client)
        assert r.text.count('data-testid="review-demo"') == 2
        assert "/swarm/demos/rep-1" in r.text and "/swarm/demos/rep-2" in r.text
        assert 'data-kind="ok"' in r.text and 'data-kind="bad"' in r.text
        assert "1 gate failed" in r.text and "Gates pass" in r.text
        assert "yesterday" in r.text and "$2.14" in r.text

    async def test_without_a_demo_the_section_is_absent(self, web):
        client, app = web
        r = await _home(client)
        assert 'data-testid="to-review"' not in r.text

    async def test_the_projects_keep_their_links_and_github_states(self, web):
        """The V2 flow's tests still hold: Connect GitHub when nothing is set
        up, the repo list with its testid otherwise."""
        client, app = web
        r = await _home(client)
        assert "Connect GitHub" in r.text
        with patch("theswarm.presentation.web.routes.common.github_app") as gh:
            gh.load_credentials = AsyncMock(return_value=None)
            gh.list_user_repositories = AsyncMock(return_value=[
                {"full_name": REPO, "description": "the test bed", "language": "Python", "pushed_at": "2026-10-06"},
            ])
            gh.oauth_client = AsyncMock(return_value=object())
            r = await client.get("/", headers=HTML)
        assert 'data-testid="repo-list"' in r.text
        assert f'href="/swarm/r/{REPO}"' in r.text and ">Internal" in r.text


# ── The sign-in page ─────────────────────────────────────────────────


class TestTheDoor:
    async def test_the_login_page_wears_the_tokens(self, web):
        client, app = web
        with patch("theswarm.presentation.web.routes.auth_routes.github_app") as gh:
            gh.oauth_client = AsyncMock(return_value=object())
            r = await client.get("/login?next=%2Fr%2Fx%2Fy")
        assert r.status_code == 200
        assert "/swarm/static/v3/app.css" in r.text
        assert "Sign in with GitHub" in r.text and 'name="access_key"' in r.text
        assert 'name="next" value="/r/x/y"' in r.text
        assert 'data-testid="rail"' not in r.text  # the doors have no rail

    async def test_an_error_is_shown(self, web):
        client, app = web
        with patch("theswarm.presentation.web.routes.auth_routes.github_app") as gh:
            gh.oauth_client = AsyncMock(return_value=None)
            r = await client.get("/login?error=Wrong+key")
        assert 'data-testid="login-error"' in r.text and "Wrong key" in r.text
        assert "Sign in with GitHub" not in r.text


# ── The pieces, on their own ─────────────────────────────────────────


class TestThePieces:
    def test_active_for_knows_home_a_project_and_a_running_cycle(self):
        from types import SimpleNamespace

        projects = [REPO, "jrechet/theswarm"]
        running = {REPO: SimpleNamespace(id="abc123abc123")}
        assert shell_mod.active_for("/swarm/", "/swarm", projects, running) == "home"
        assert shell_mod.active_for("/swarm", "/swarm", projects, running) == "home"
        assert shell_mod.active_for(f"/swarm/r/{REPO}", "/swarm", projects, running) == REPO
        assert shell_mod.active_for(f"/swarm/r/{REPO}/memory", "/swarm", projects, running) == REPO
        assert shell_mod.active_for("/swarm/c/abc123abc123", "/swarm", projects, running) == REPO
        assert shell_mod.active_for("/swarm/c/other", "/swarm", projects, running) == ""
        assert shell_mod.active_for("/r/jrechet/theswarm", "", projects, running) == "jrechet/theswarm"

    def test_the_build_and_the_image_compile_the_v3_stylesheet(self):
        script = (ROOT / "scripts" / "build-css.sh").read_text()
        dockerfile = (ROOT / "Dockerfile").read_text()
        assert "static/v3/input.css" in script and "static/v3/app.css" in script
        assert "static/v3/input.css" in dockerfile and "static/v3/app.css" in dockerfile
        assert "static/v2/app.css" not in dockerfile
        assert "**/static/v3/app.css" in (ROOT / ".gitignore").read_text()

    def test_the_fonts_are_vendored_with_their_licence(self):
        fonts = WEB / "static" / "v3" / "fonts"
        assert (fonts / "Geist-Variable.woff2").stat().st_size > 10_000
        assert (fonts / "GeistMono-Variable.woff2").stat().st_size > 10_000
        assert "SIL Open Font License" in (fonts / "LICENSE.txt").read_text()
        css = (WEB / "static" / "v3" / "input.css").read_text()
        assert 'url("fonts/Geist-Variable.woff2")' in css and "googleapis" not in css

    def test_the_tokens_carry_both_themes_and_no_v2_alias(self):
        css = (WEB / "static" / "v3" / "input.css").read_text()
        for token in ("--canvas", "--surface", "--line", "--ink", "--live", "--ok", "--bad", "--info", "--wait"):
            assert f"{token}:" in css
        assert '@media (prefers-color-scheme: dark)' in css and ':root[data-theme="dark"]' in css
        assert "--color-honey" not in css and "--color-rule" not in css  # the V2 aliases went with V2 (M6)


class TestThePhonePass:
    """M7: the shell on a phone — the rail's foot reaches a narrow screen,
    and an address that does not exist is a page, not JSON, for a browser."""

    async def test_the_rail_s_foot_is_not_hidden_on_a_phone(self, web):
        client, _ = web
        with patch("theswarm.presentation.web.routes.common.github_app") as gh:
            gh.load_credentials = AsyncMock(return_value=None)
            gh.list_user_repositories = AsyncMock(return_value=[])
            gh.oauth_client = AsyncMock(return_value=object())
            r = await client.get("/", headers=HTML)
        assert r.status_code == 200
        foot = re.search(r'<div class="([^"]*)" data-testid="rail-foot">', r.text)
        assert foot and "hidden" not in foot.group(1).split() and "md:flex-col" in foot.group(1)

    async def test_an_unknown_address_is_a_page_for_a_browser_and_json_for_a_client(self, web):
        client, _ = web
        r = await client.get("/dashboard", headers=HTML)
        assert r.status_code == 404 and 'data-testid="not-found"' in r.text and 'data-testid="rail-home"' in r.text
        assert "/dashboard" in r.text and 'data-testid="not-found-home"' in r.text
        r = await client.get("/dashboard", headers={"accept": "application/json"})
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        r = await client.get("/c/nobody", headers=HTML)
        assert r.status_code == 404 and 'data-testid="not-found"' in r.text
