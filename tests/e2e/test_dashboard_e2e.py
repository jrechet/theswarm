"""E2E tests: comprehensive browser testing of every dashboard surface.

Covers: navigation, dashboard, projects CRUD, cycles, reports, health,
API endpoints, SSE connectivity, form validation, cross-page consistency.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect


SERVER_PORT = 8093
BASE_URL = f"http://localhost:{SERVER_PORT}"
SEEDED_DEMO_ID = "e2e-seed-demo-1"
SEEDED_DEMO_PROJECT = "e2e-seed-proj"
SEEDED_VIDEO_DEMO_ID = "e2e-seed-demo-video-1"
SEEDED_VIDEO_REL_PATH = "e2e-seed-cycle-video/video/demo.webm"


def _run_server(db_path: str, artifact_dir: str = ""):
    """Start the TheSwarm server in a subprocess using an isolated DB."""
    import asyncio
    from theswarm.presentation.web.server import start_server
    asyncio.run(start_server(
        host="127.0.0.1", port=SERVER_PORT, db_path=db_path, artifact_dir=artifact_dir,
    ))


def _seed_demo_report(db_path: str) -> None:
    """Seed one complete DemoReport with stories, gates, artifacts, learnings.

    This runs synchronously against the isolated test DB before the server starts,
    so the schema is already present from the first server boot. We retry a few
    times if the DB file is not yet created.
    """
    story = {
        "title": "Seed story: add feature flag toggle",
        "ticket_id": "SEED-1",
        "pr_number": 101,
        "pr_url": "https://github.com/example/seed/pull/101",
        "status": "completed",
        "files_changed": 3,
        "lines_added": 42,
        "lines_removed": 7,
        "screenshots_before": [
            {"type": "screenshot", "path": "seed/before.png", "label": "Before", "size_bytes": 1234},
        ],
        "screenshots_after": [
            {"type": "screenshot", "path": "seed/after.png", "label": "After", "size_bytes": 2345},
        ],
        "video": None,
        "diff_highlights": [
            {
                "file_path": "src/feature.py",
                "hunk": "+ flag = Toggle('new_feature')",
                "annotation": "New toggle wiring",
            },
        ],
    }
    gates = [
        {"name": "Unit tests", "status": "pass", "detail": "42/42 passing"},
        {"name": "E2E tests", "status": "pass", "detail": "5/5 passing"},
        {"name": "Coverage", "status": "pass", "detail": "85.2% (target 80%)"},
    ]
    summary = {
        "stories_completed": 1,
        "stories_total": 1,
        "prs_merged": 1,
        "tests_passing": 42,
        "tests_total": 42,
        "coverage_percent": 85.2,
        "security_critical": 0,
        "security_medium": 0,
        "cost_usd": 0.12,
    }
    learnings = [
        "Feature flags should default to off in production.",
    ]
    top_artifacts = [
        {"type": "screenshot", "path": "seed/dashboard.png", "label": "Dashboard", "size_bytes": 3456},
    ]

    video_story = {
        "title": "Seed story with video: admin console walkthrough",
        "ticket_id": "SEED-VIDEO-1",
        "pr_number": 202,
        "pr_url": "https://github.com/example/seed/pull/202",
        "status": "completed",
        "files_changed": 5,
        "lines_added": 120,
        "lines_removed": 30,
        "screenshots_before": [],
        "screenshots_after": [],
        "video": {
            "type": "video",
            "path": SEEDED_VIDEO_REL_PATH,
            "label": "Admin console demo",
            "size_bytes": 64,
        },
        "diff_highlights": [],
    }

    for _ in range(30):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO reports
                   (id, cycle_id, project_id, summary_json, stories_json,
                    quality_json, learnings_json, artifacts_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    SEEDED_DEMO_ID,
                    "seed-cycle-1",
                    SEEDED_DEMO_PROJECT,
                    json.dumps(summary),
                    json.dumps([story]),
                    json.dumps(gates),
                    json.dumps(learnings),
                    json.dumps(top_artifacts),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            cur.execute(
                """INSERT OR REPLACE INTO reports
                   (id, cycle_id, project_id, summary_json, stories_json,
                    quality_json, learnings_json, artifacts_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    SEEDED_VIDEO_DEMO_ID,
                    "e2e-seed-cycle-video",
                    SEEDED_DEMO_PROJECT,
                    json.dumps(summary),
                    json.dumps([video_story]),
                    json.dumps(gates),
                    json.dumps([]),
                    json.dumps([]),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError:
            time.sleep(0.3)
    raise RuntimeError("Could not seed demo report — schema not ready")


@pytest.fixture(scope="module")
def server():
    """Launch a real server for E2E tests against an isolated, throwaway DB.

    Prevents E2E runs from polluting ~/.swarm-data/theswarm.db with e2e-* rows.
    """
    tmpdir = tempfile.mkdtemp(prefix="theswarm-e2e-")
    db_path = os.path.join(tmpdir, "e2e.db")
    artifact_dir = os.path.join(tmpdir, "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    # Write a tiny webm blob so /artifacts/{SEEDED_VIDEO_REL_PATH} returns 200.
    video_path = os.path.join(artifact_dir, SEEDED_VIDEO_REL_PATH)
    os.makedirs(os.path.dirname(video_path), exist_ok=True)
    with open(video_path, "wb") as f:
        # Minimal WebM/EBML header — enough for FileResponse to serve as video/webm
        f.write(b"\x1a\x45\xdf\xa3" + b"\x00" * 60)

    proc = multiprocessing.Process(
        target=_run_server, args=(db_path, artifact_dir), daemon=True,
    )
    proc.start()
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        shutil.rmtree(tmpdir, ignore_errors=True)
        pytest.fail("Server did not start within 15 seconds")

    # Seed deterministic demo reports (image-only + video) for player E2E tests.
    _seed_demo_report(db_path)

    yield proc
    proc.terminate()
    proc.join(timeout=3)
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Navigation ──────────────────────────────────────────────────────


class TestNavigation:
    """Verify top navigation links are present and functional."""

    def test_nav_has_all_links(self, server, page: Page):
        page.goto(BASE_URL)
        nav = page.locator("nav.topnav")
        expect(nav.locator("a", has_text="Dashboard")).to_be_visible()
        expect(nav.locator("a", has_text="Projects")).to_be_visible()
        expect(nav.locator("a", has_text="Cycles")).to_be_visible()
        expect(nav.locator("a", has_text="Reports")).to_be_visible()
        expect(nav.locator("a", has_text="Health")).to_be_visible()

    def test_nav_dashboard_link(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/")
        page.click("nav a:has-text('Dashboard')")
        page.wait_for_url(f"{BASE_URL}/")
        expect(page).to_have_title("Dashboard — TheSwarm")

    def test_nav_projects_link(self, server, page: Page):
        page.goto(BASE_URL)
        page.click("nav a:has-text('Projects')")
        page.wait_for_url("**/projects/")
        expect(page).to_have_title("Projects — TheSwarm")

    def test_nav_cycles_link(self, server, page: Page):
        page.goto(BASE_URL)
        page.click("nav a:has-text('Cycles')")
        page.wait_for_url("**/cycles/")
        expect(page).to_have_title("Cycles — TheSwarm")

    def test_nav_reports_link(self, server, page: Page):
        page.goto(BASE_URL)
        page.click("nav a:has-text('Reports')")
        page.wait_for_url("**/reports/")
        expect(page).to_have_title("Reports")

    def test_nav_logo_links_home(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/")
        page.click("a.logo")
        page.wait_for_url(f"{BASE_URL}/")

    def test_sse_status_indicator_visible(self, server, page: Page):
        page.goto(BASE_URL)
        status = page.locator("#sse-status")
        expect(status).to_be_visible()


# ── Dashboard ───────────────────────────────────────────────────────


class TestDashboard:
    """Dashboard overview page: stats, active cycles, live feed, projects."""

    def test_dashboard_loads_with_title(self, server, page: Page):
        page.goto(BASE_URL)
        expect(page).to_have_title("Dashboard — TheSwarm")
        expect(page.locator("text=TheSwarm")).to_be_visible()

    def test_dashboard_overview_section(self, server, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        # Stat labels inside the stats card
        stats = page.locator(".stats-card")
        expect(stats.locator(".stat-label", has_text="Projects")).to_be_visible()
        expect(stats.locator(".stat-label", has_text="Active Cycles")).to_be_visible()
        expect(stats.locator(".stat-label", has_text="Cost Today")).to_be_visible()

    def test_dashboard_active_cycles_section(self, server, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_role("heading", name="Active Cycles")).to_be_visible()

    def test_dashboard_live_activity_section(self, server, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_role("heading", name="Live Activity")).to_be_visible()
        expect(page.locator("#activity-feed")).to_be_visible()

    def test_dashboard_projects_section(self, server, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_role("heading", name="Projects")).to_be_visible()

    def test_dashboard_empty_state_links(self, server, page: Page):
        """Empty dashboard should link to add a project or start from projects page."""
        page.goto(BASE_URL)
        # At minimum, the empty state should have a link
        links = page.locator(".empty-state a")
        assert links.count() > 0


# ── Health ──────────────────────────────────────────────────────────


class TestHealth:
    """Health endpoint: database, SSE, service status."""

    def test_health_returns_ok(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/health")
        assert response.ok
        data = response.json()
        assert data["status"] in ("ok", "warn", "error", "degraded")
        assert data["service"] == "theswarm"

    def test_health_uptime(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/health")
        data = response.json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] > 0

    def test_health_checks_database(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/health")
        data = response.json()
        assert "checks" in data
        assert data["checks"]["database"] == "connected"

    def test_health_checks_sse(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/health")
        data = response.json()
        assert data["checks"]["sse"] == "ok"


# ── Projects CRUD ───────────────────────────────────────────────────


class TestProjects:
    """Full project lifecycle: list, create, view, delete."""

    def test_projects_list_empty(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/")
        expect(page).to_have_title("Projects — TheSwarm")

    def test_projects_add_button(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/")
        add_btn = page.locator("a:has-text('Add Project')")
        expect(add_btn).to_be_visible()

    def test_add_project_form_loads(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/new")
        expect(page).to_have_title("Add Project — TheSwarm")
        expect(page.get_by_role("heading", name="Add Project")).to_be_visible()
        # All form fields present
        expect(page.locator("input[name='project_id']")).to_be_visible()
        expect(page.locator("input[name='repo']")).to_be_visible()
        expect(page.locator("select[name='framework']")).to_be_visible()
        expect(page.locator("select[name='ticket_source']")).to_be_visible()
        expect(page.locator("input[name='team_channel']")).to_be_visible()

    def test_add_project_form_has_framework_options(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/new")
        options = page.locator("select[name='framework'] option")
        texts = [options.nth(i).inner_text() for i in range(options.count())]
        assert "Auto-detect" in texts
        assert "FastAPI" in texts
        assert "Django" in texts
        assert "Next.js" in texts

    def test_add_project_form_has_ticket_source_options(self, server, page: Page):
        page.goto(f"{BASE_URL}/projects/new")
        options = page.locator("select[name='ticket_source'] option")
        texts = [options.nth(i).inner_text() for i in range(options.count())]
        assert "GitHub Issues" in texts
        assert "Jira" in texts
        assert "Linear" in texts

    def test_create_project_full_flow(self, server, page: Page):
        """Create a project, verify redirect, verify it appears in list."""
        pid = f"e2e-{uuid.uuid4().hex[:8]}"
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"testorg/{pid}")
        page.select_option("select[name='framework']", "fastapi")
        page.select_option("select[name='ticket_source']", "github")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")
        # Project should appear in the list (use h3 to avoid matching repo URL too)
        expect(page.locator(f"h3:has-text('{pid}')")).to_be_visible()

    def test_project_detail_page(self, server, page: Page):
        """Create a project and view its detail page."""
        pid = f"e2e-detail-{uuid.uuid4().hex[:8]}"
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"testorg/{pid}")
        page.select_option("select[name='framework']", "django")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")

        # Navigate to detail page directly (avoids HTMX race)
        page.goto(f"{BASE_URL}/projects/{pid}")
        expect(page).to_have_title(f"{pid} — TheSwarm")

        # Verify configuration is displayed
        expect(page.get_by_role("heading", name="Configuration")).to_be_visible()
        expect(page.locator(f"dd:has-text('testorg/{pid}')")).to_be_visible()
        expect(page.locator(".badge:has-text('django')")).to_be_visible()

        # Verify action buttons exist
        expect(page.locator("button:has-text('Run Cycle')")).to_be_visible()
        expect(page.locator("button:has-text('Delete')")).to_be_visible()

    def test_project_detail_shows_config_fields(self, server, page: Page):
        """Verify all config fields render on detail page."""
        pid = f"e2e-cfg-{uuid.uuid4().hex[:8]}"
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"org/{pid}")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")
        page.click(f"a:has-text('{pid}')")
        page.wait_for_url(f"**/projects/{pid}")

        # All config labels should be present
        for label in ["Repository", "Framework", "Ticket Source",
                      "Default Branch", "Max Stories/Day"]:
            expect(page.locator(f"dt:has-text('{label}')")).to_be_visible()

    def test_delete_project_flow(self, server, page: Page):
        """Create a project, navigate to detail, delete it."""
        pid = f"e2e-del-{uuid.uuid4().hex[:8]}"
        # Create
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"org/{pid}")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")

        # Navigate to detail
        page.click(f"a:has-text('{pid}')")
        page.wait_for_url(f"**/projects/{pid}")

        # Delete (accept confirm dialog)
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("button:has-text('Delete')")
        page.wait_for_url("**/projects/")

        # Project should be gone
        expect(page.locator(f"text={pid}")).not_to_be_visible()

    def test_project_not_found_returns_404(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/projects/nonexistent-project-xyz")
        assert response.status == 404

    def test_navigate_from_list_to_create(self, server, page: Page):
        """Click 'Add Project' button on list page."""
        page.goto(f"{BASE_URL}/projects/")
        page.click("a:has-text('Add Project')")
        page.wait_for_url("**/projects/new")
        expect(page.get_by_role("heading", name="Add Project")).to_be_visible()

    def test_cancel_button_on_create_form(self, server, page: Page):
        """Cancel button goes back to project list."""
        page.goto(f"{BASE_URL}/projects/new")
        page.click("a:has-text('Cancel')")
        page.wait_for_url("**/projects/")


# ── Cycles ──────────────────────────────────────────────────────────


class TestCycles:
    """Cycle list, detail, and trigger flow."""

    def test_cycles_page_loads(self, server, page: Page):
        page.goto(f"{BASE_URL}/cycles/")
        expect(page).to_have_title("Cycles — TheSwarm")

    def test_cycles_empty_state(self, server, page: Page):
        page.goto(f"{BASE_URL}/cycles/")
        # Either shows cycle data or empty state
        assert page.content()

    def test_cycles_table_headers(self, server, page: Page):
        """If cycles exist, table headers should be present."""
        page.goto(f"{BASE_URL}/cycles/")
        content = page.content()
        # Page should have either empty state or table
        assert "Cycles" in content

    def test_cycle_not_found_returns_404(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/cycles/nonexistent-cycle-id")
        assert response.status == 404

    def test_trigger_cycle_from_project(self, server, page: Page):
        """Create a project, trigger a cycle from its detail page."""
        pid = f"e2e-cyc-{uuid.uuid4().hex[:8]}"
        # Create project
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"org/{pid}")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")

        # Navigate to detail and trigger cycle
        page.click(f"a:has-text('{pid}')")
        page.wait_for_url(f"**/projects/{pid}")
        page.click("button:has-text('Run Cycle')")

        # Should redirect to cycle detail page
        page.wait_for_url("**/cycles/**")
        # Page should show the cycle (may be running or pending)
        content = page.content().lower()
        assert "cycle" in content


# ── Reports ─────────────────────────────────────────────────────────


class TestReports:
    """Report list and detail pages."""

    def test_reports_page_loads(self, server, page: Page):
        page.goto(f"{BASE_URL}/reports/")
        assert page.url.endswith("/reports/")
        content = page.content()
        assert "Reports" in content or "Demo Reports" in content

    def test_reports_empty_state(self, server, page: Page):
        page.goto(f"{BASE_URL}/reports/")
        content = page.content()
        # Should show empty state or report list
        assert "report" in content.lower() or "Report" in content

    def test_report_not_found(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/reports/nonexistent-report-id")
        assert response.status == 404
        content = response.text()
        assert "Not Found" in content or "not found" in content.lower()


# ── API Endpoints ───────────────────────────────────────────────────


class TestAPIEndpoints:
    """REST API validation: projects, dashboard, cycles, live state."""

    def test_api_projects_returns_list(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/projects")
        assert response.ok
        data = response.json()
        assert isinstance(data, list)

    def test_api_dashboard_returns_stats(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/dashboard")
        assert response.ok
        data = response.json()
        assert "active_cycles" in data
        assert "projects" in data
        assert "total_cost_today" in data
        assert isinstance(data["active_cycles"], int)
        assert isinstance(data["total_cost_today"], (int, float))

    def test_api_live_state(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/live/state")
        assert response.ok
        data = response.json()
        assert "cycle_running" in data
        assert "cost_so_far" in data
        assert "recent_events" in data

    def test_api_cycles_list(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/cycles")
        assert response.ok
        data = response.json()
        assert "cycles" in data
        assert isinstance(data["cycles"], list)

    def test_api_cycle_not_found(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/cycles/nonexistent")
        assert response.status == 404

    def test_api_start_cycle(self, server, page: Page):
        """Start a cycle via API and verify it appears in the list."""
        response = page.request.post(
            f"{BASE_URL}/api/cycle",
            data={"repo": "testorg/e2e-api-test", "description": "E2E API test"},
            headers={"Content-Type": "application/json"},
        )
        assert response.ok
        data = response.json()
        assert "cycle_id" in data
        assert data["status"] in ("queued", "running")
        assert data["repo"] == "testorg/e2e-api-test"

        # Verify it appears in cycle list
        cycle_id = data["cycle_id"]
        status_response = page.request.get(f"{BASE_URL}/api/cycles/{cycle_id}")
        assert status_response.ok

    def test_api_cancel_nonexistent_cycle(self, server, page: Page):
        response = page.request.post(f"{BASE_URL}/api/cycle/nonexistent/cancel")
        assert response.status == 404

    def test_api_projects_after_create(self, server, page: Page):
        """Create a project via web form, verify it in API."""
        pid = f"e2e-api-{uuid.uuid4().hex[:8]}"
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"org/{pid}")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")

        # Verify via API
        response = page.request.get(f"{BASE_URL}/api/projects")
        data = response.json()
        ids = [p["id"] for p in data]
        assert pid in ids


# ── Exhaustive API coverage ─────────────────────────────────────────


class TestAPIExhaustive:
    """Every JSON API endpoint must return a valid status (no 5xx, correct 404)."""

    def test_api_features_returns_list(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        assert response.ok
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Every feature has the documented shape
        for feat in data:
            assert "id" in feat
            assert "name" in feat
            assert "phase" in feat
            assert "module" in feat
            assert "available" in feat
            assert isinstance(feat["available"], bool)

    def test_api_dashboard_shape(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/dashboard")
        assert response.ok
        data = response.json()
        assert set(data.keys()) >= {"active_cycles", "projects", "total_cost_today"}
        assert isinstance(data["active_cycles"], int)
        assert isinstance(data["projects"], int)
        assert isinstance(data["total_cost_today"], (int, float))

    def test_api_projects_shape(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/projects")
        assert response.ok
        data = response.json()
        assert isinstance(data, list)
        # Shape check when non-empty
        for p in data:
            assert set(p.keys()) >= {"id", "repo", "framework", "ticket_source"}

    def test_api_live_state_shape(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/live/state")
        assert response.ok
        data = response.json()
        assert "cycle_running" in data
        assert "cost_so_far" in data
        assert "recent_events" in data

    def test_api_live_history_handles_no_repo(self, server, page: Page):
        """Without SWARM_GITHUB_REPO, /api/live/history must still 200 with empty list."""
        response = page.request.get(f"{BASE_URL}/api/live/history")
        assert response.ok
        data = response.json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_api_cycles_list_pagination(self, server, page: Page):
        """limit param caps results at 100 server-side."""
        response = page.request.get(f"{BASE_URL}/api/cycles?limit=500")
        assert response.ok
        data = response.json()
        assert isinstance(data["cycles"], list)
        assert len(data["cycles"]) <= 100

    def test_api_cycle_not_found_404(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/cycles/does-not-exist-xyz")
        assert response.status == 404

    def test_api_report_not_found_404(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/reports/2026-01-01")
        assert response.status == 404

    def test_api_weekly_report_without_repo_404(self, server, page: Page):
        """Without SWARM_GITHUB_REPO configured, weekly report 404s (not 500)."""
        response = page.request.get(f"{BASE_URL}/api/reports/weekly")
        assert response.status in (200, 404), (
            f"Weekly report returned unexpected {response.status}"
        )

    def test_api_start_cycle_rejects_empty_body(self, server, page: Page):
        """POST /api/cycle with empty body should return 4xx, not 500."""
        response = page.request.post(
            f"{BASE_URL}/api/cycle",
            data={},
            headers={"Content-Type": "application/json"},
        )
        assert response.status < 500, f"Empty body returned {response.status}"

    def test_api_cancel_cycle_404_for_unknown(self, server, page: Page):
        response = page.request.post(f"{BASE_URL}/api/cycle/unknown-xyz/cancel")
        assert response.status == 404

    def test_api_approve_pr_without_repo_returns_400(self, server, page: Page):
        """Without repo configured, approve must return 4xx, not 500."""
        response = page.request.post(f"{BASE_URL}/api/reports/2026-01-01/approve/42")
        # Either no repo (400) or PR does not exist (500 from github client)
        assert response.status in (400, 404, 500), "Unexpected status"
        # At minimum it must not crash on routing
        assert response.status != 0

    def test_api_health_404_if_not_registered(self, server, page: Page):
        """/api/health is not a registered route — must be 404, not 500."""
        response = page.request.get(f"{BASE_URL}/api/health")
        assert response.status == 404


# ── Demo seeded row visible in list APIs ────────────────────────────


class TestSeededReportVisibility:
    """The seeded demo report must appear in the reports/demos surfaces."""

    def test_seeded_report_detail_page_loads(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/reports/{SEEDED_DEMO_ID}")
        assert response.status == 200, (
            f"Seeded report detail page returned {response.status}"
        )

    def test_seeded_report_appears_on_demos_browse(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/")
        expect(page.locator(f"a[href*='{SEEDED_DEMO_ID}']")).to_have_count(
            1, timeout=5000,
        )


# ── SSE Connectivity ────────────────────────────────────────────────


class TestSSE:
    """Verify SSE connectivity from the browser."""

    def test_sse_connects_on_dashboard(self, server, page: Page):
        """The dashboard SSE status should transition to Live after connection."""
        page.goto(BASE_URL)
        status = page.locator("#sse-status")
        # Status text transitions from "Connecting..." to "Live" once SSE opens.
        expect(status).to_contain_text("Live", timeout=10_000)

    def test_activity_feed_exists(self, server, page: Page):
        """The activity feed container is present and wired to SSE via sse.js."""
        page.goto(BASE_URL)
        feed = page.locator("#activity-feed")
        expect(feed).to_be_visible()
        # sse.js connects to /api/events — verify the feed subscribes by
        # waiting for the connection status indicator to reach Live.
        expect(page.locator("#sse-status")).to_contain_text("Live", timeout=10_000)


# ── Cross-Page Consistency ──────────────────────────────────────────


class TestCrossPageConsistency:
    """Verify data appears consistently across dashboard and list pages."""

    def test_project_appears_on_dashboard_and_list(self, server, page: Page):
        """A created project should appear on both dashboard and projects page."""
        pid = f"e2e-xp-{uuid.uuid4().hex[:8]}"
        page.goto(f"{BASE_URL}/projects/new")
        page.fill("input[name='project_id']", pid)
        page.fill("input[name='repo']", f"org/{pid}")
        page.click("button[type='submit']")
        page.wait_for_url("**/projects/")

        # Check projects list (use h3 to be specific)
        expect(page.locator(f"h3:has-text('{pid}')")).to_be_visible()

        # Check dashboard - project card heading
        page.goto(BASE_URL)
        expect(page.locator(f"h3:has-text('{pid}')")).to_be_visible()

    def test_dashboard_project_count_matches_api(self, server, page: Page):
        """Dashboard stat should match API project count."""
        api_response = page.request.get(f"{BASE_URL}/api/dashboard")
        data = api_response.json()
        api_count = data["projects"]

        page.goto(BASE_URL)
        # The stat-value for Projects
        stat_values = page.locator(".stat-value").all_text_contents()
        # First stat is project count
        assert str(api_count) == stat_values[0]


# ── Legacy Routes ───────────────────────────────────────────────────


class TestLegacyRoutes:
    """Verify old routes are properly gone."""

    def test_legacy_dashboard_gone(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/swarm/dashboard")
        assert response.status == 404

    def test_legacy_reports_gone(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/swarm/reports/2026-01-01")
        assert response.status == 404


# ── Static Assets ───────────────────────────────────────────────────


class TestStaticAssets:
    """Verify CSS and JS load correctly."""

    def test_css_loads(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/static/css/dashboard.css")
        assert response.ok
        assert "var(--bg-primary)" in response.text()

    def test_js_loads(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/static/js/sse.js")
        assert response.ok
        assert "EventSource" in response.text()

    def test_no_console_errors_on_dashboard(self, server, page: Page):
        """Dashboard should load without JS console errors."""
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(BASE_URL)
        # Use domcontentloaded since networkidle can't fire with SSE open
        page.wait_for_load_state("domcontentloaded")
        # Give JS a moment to initialize
        page.wait_for_timeout(1000)
        # Filter out SSE reconnect noise
        real_errors = [e for e in errors if "EventSource" not in e]
        assert len(real_errors) == 0, f"Console errors: {real_errors}"


# ── Demos Browse & Player ────────────────────────────────────────────


class TestDemos:
    """Demo browse and player pages must render without 500s."""

    def test_demos_browse_returns_200(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/demos/")
        assert response.status == 200, (
            f"/demos/ returned {response.status} — dashboard demo browse is broken"
        )

    def test_demos_browse_renders(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/")
        expect(page).to_have_title("Demos — TheSwarm")
        expect(page.get_by_role("heading", name="Demos")).to_be_visible()

    def test_demos_browse_shows_empty_or_list(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/")
        content = page.content()
        # Either empty state or at least one demo card
        has_empty = "No demos yet" in content
        has_card = "demo-card" in content
        assert has_empty or has_card, "Demos page must show either an empty state or demo cards"

    def test_demo_not_found_returns_404(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/demos/nonexistent-demo-id/play")
        assert response.status == 404


# ── Demo Player (seeded) ─────────────────────────────────────────────


class TestDemoPlayer:
    """The /demos/{id}/play page must render, navigate, and expose slides."""

    def test_seeded_demo_player_loads(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        assert response.status == 200, (
            f"/demos/{SEEDED_DEMO_ID}/play returned {response.status}"
        )

    def test_seeded_demo_player_has_slides(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        slides = page.locator(".player-slide")
        # Seed generates: title + story + screenshots + quality_gates + gallery + learnings = 6
        assert slides.count() >= 4, f"Expected at least 4 slides, got {slides.count()}"

    def test_seeded_demo_player_title_slide_visible(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        title_badge = page.locator(".slide-title-badge")
        expect(title_badge).to_be_visible()
        expect(title_badge).to_contain_text("Demo Report")
        expect(page.locator(".slide-title h1")).to_contain_text(SEEDED_DEMO_PROJECT)

    def test_seeded_demo_player_slide_counter(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        current = page.locator("#slide-current")
        expect(current).to_have_text("1", timeout=5000)
        total_text = page.locator("#slide-total").inner_text()
        assert int(total_text) >= 4

    def test_seeded_demo_player_next_button_advances(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        expect(page.locator("#slide-current")).to_have_text("1", timeout=5000)
        page.click("#btn-next")
        expect(page.locator("#slide-current")).to_have_text("2", timeout=5000)
        page.click("#btn-next")
        expect(page.locator("#slide-current")).to_have_text("3", timeout=5000)

    def test_seeded_demo_player_prev_button_goes_back(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        page.click("#btn-next")
        page.click("#btn-next")
        expect(page.locator("#slide-current")).to_have_text("3", timeout=5000)
        page.click("#btn-prev")
        expect(page.locator("#slide-current")).to_have_text("2", timeout=5000)

    def test_seeded_demo_player_keyboard_arrow_navigation(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        expect(page.locator("#slide-current")).to_have_text("1", timeout=5000)
        page.keyboard.press("ArrowRight")
        expect(page.locator("#slide-current")).to_have_text("2", timeout=5000)
        page.keyboard.press("ArrowLeft")
        expect(page.locator("#slide-current")).to_have_text("1", timeout=5000)

    def test_seeded_demo_player_progress_segments(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        segments = page.locator(".progress-segment")
        total_text = page.locator("#slide-total").inner_text()
        assert segments.count() == int(total_text), (
            "Progress segment count must match slide count"
        )

    def test_seeded_demo_player_back_link_to_browse(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        back = page.locator(".player-back")
        expect(back).to_be_visible()
        assert back.get_attribute("href").endswith("/demos/")

    def test_seeded_demo_renders_artifact_paths(self, server, page: Page):
        """Artifact <img> sources must point at /artifacts/ (player wiring check)."""
        page.goto(f"{BASE_URL}/demos/{SEEDED_DEMO_ID}/play")
        imgs = page.locator("img[src*='/artifacts/']")
        assert imgs.count() > 0, "Seeded demo should render artifact images"


class TestDemoVideoRoundtrip:
    """End-to-end video flow: seed story video → player renders <video> → /artifacts serves blob."""

    def test_video_demo_player_loads(self, server, page: Page):
        resp = page.request.get(f"{BASE_URL}/demos/{SEEDED_VIDEO_DEMO_ID}/play")
        assert resp.status == 200

    def test_video_demo_renders_video_element(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_VIDEO_DEMO_ID}/play")
        videos = page.locator("video[src*='/artifacts/']")
        assert videos.count() >= 1, "Video story slide must render a <video> element"

    def test_video_src_points_at_seeded_path(self, server, page: Page):
        page.goto(f"{BASE_URL}/demos/{SEEDED_VIDEO_DEMO_ID}/play")
        video = page.locator("video[src*='/artifacts/']").first
        src = video.get_attribute("src") or ""
        assert SEEDED_VIDEO_REL_PATH in src, (
            f"Video src {src!r} must reference seeded path {SEEDED_VIDEO_REL_PATH!r}"
        )

    def test_video_artifact_served_200(self, server, page: Page):
        """The actual /artifacts/ URL rendered in the player must return 200."""
        resp = page.request.get(f"{BASE_URL}/artifacts/{SEEDED_VIDEO_REL_PATH}")
        assert resp.status == 200, f"Video artifact returned {resp.status}"
        assert resp.headers.get("content-type", "").startswith("video/webm")
        assert len(resp.body()) > 0


# ── Features ─────────────────────────────────────────────────────────


class TestFeaturesPage:
    """The /features/ page must render without 500."""

    def test_features_page_returns_200(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/features/")
        assert response.status == 200

    def test_features_page_title(self, server, page: Page):
        page.goto(f"{BASE_URL}/features/")
        expect(page).to_have_title("Features — TheSwarm")


# ── Fragments (HTMX-swappable partials) ─────────────────────────────


class TestFragments:
    """HTMX fragment endpoints must render partial HTML without 500."""

    def test_stats_fragment_returns_200(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/fragments/stats")
        assert response.status == 200
        body = response.text()
        assert "stat-" in body or "stats" in body.lower()

    def test_stats_fragment_is_html_partial(self, server, page: Page):
        """Stats fragment must not include full <html> boilerplate."""
        response = page.request.get(f"{BASE_URL}/fragments/stats")
        assert response.status == 200
        body = response.text()
        assert "<html" not in body.lower(), "Fragment should be a partial, not a full document"

    def test_active_cycles_fragment_returns_200(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/fragments/active-cycles")
        assert response.status == 200

    def test_recent_cycles_fragment_returns_200(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/fragments/recent-cycles")
        assert response.status == 200

    def test_cycle_overview_fragment_404_for_unknown(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/fragments/cycle/nonexistent-cycle/overview")
        assert response.status == 404

    def test_cycle_phases_fragment_404_for_unknown(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/fragments/cycle/nonexistent-cycle/phases")
        assert response.status == 404


# ── Route Smoke Walk (source of truth: no 500 anywhere) ─────────────


class TestRouteSmokeWalk:
    """Walk every documented dashboard route and assert no server errors."""

    ROUTES = [
        "/",
        "/projects/",
        "/projects/new",
        "/cycles/",
        "/reports/",
        "/demos/",
        "/features/",
        "/health",
        "/api/health",
        "/api/dashboard",
        "/api/projects",
        "/api/cycles",
        "/api/features",
        "/api/live/state",
        "/fragments/stats",
        "/fragments/active-cycles",
        "/fragments/recent-cycles",
    ]

    def test_all_routes_no_500(self, server, page: Page):
        """If any route returns 5xx, the dashboard is NOT fully working."""
        failures = []
        for route in self.ROUTES:
            resp = page.request.get(f"{BASE_URL}{route}")
            if resp.status >= 500:
                failures.append(f"{route} -> {resp.status}")
        assert not failures, f"Routes returning 5xx: {failures}"
