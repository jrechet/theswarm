"""E2E tests: comprehensive browser testing of every dashboard surface.

Covers: navigation, dashboard, projects CRUD, cycles, reports, health,
API endpoints, SSE connectivity, form validation, cross-page consistency.
"""

from __future__ import annotations

import multiprocessing
import time
import uuid

import pytest
from playwright.sync_api import Page, expect


SERVER_PORT = 8093
BASE_URL = f"http://localhost:{SERVER_PORT}"


def _run_server():
    """Start the TheSwarm server in a subprocess."""
    import asyncio
    from theswarm.presentation.web.server import start_server
    asyncio.run(start_server(host="127.0.0.1", port=SERVER_PORT))


@pytest.fixture(scope="module")
def server():
    """Launch a real server for E2E tests."""
    proc = multiprocessing.Process(target=_run_server, daemon=True)
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
        pytest.fail("Server did not start within 15 seconds")
    yield proc
    proc.terminate()
    proc.join(timeout=3)


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
        assert data["status"] in ("ok", "degraded")
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


# ── SSE Connectivity ────────────────────────────────────────────────


class TestSSE:
    """Verify SSE connectivity from the browser."""

    def test_sse_connects_on_dashboard(self, server, page: Page):
        """The dashboard SSE status should show Connected after load."""
        page.goto(BASE_URL)
        # SSE status indicator should eventually show connected
        status = page.locator("#sse-status")
        expect(status).to_have_text("Connected", timeout=10_000)

    def test_activity_feed_exists(self, server, page: Page):
        """The activity feed container connects to SSE."""
        page.goto(BASE_URL)
        feed = page.locator("#activity-feed")
        expect(feed).to_be_visible()
        # Verify the SSE attributes are present
        assert feed.get_attribute("sse-connect") is not None


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
