"""E2E tests: verify all dashboard routes are accessible via browser."""

from __future__ import annotations

import asyncio
import multiprocessing
import time

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
    # Wait for server to be ready
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


# ── Dashboard ────────────────────────────────────────────────────────


def test_dashboard_loads(server, page: Page):
    page.goto(BASE_URL)
    expect(page).to_have_title("Dashboard — TheSwarm")
    expect(page.locator("text=TheSwarm")).to_be_visible()
    expect(page.locator("text=Overview")).to_be_visible()


def test_dashboard_shows_projects_section(server, page: Page):
    page.goto(BASE_URL)
    expect(page.get_by_role("heading", name="Projects")).to_be_visible()


# ── Health ───────────────────────────────────────────────────────────


def test_health_endpoint(server, page: Page):
    response = page.request.get(f"{BASE_URL}/health")
    assert response.ok
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["service"] == "theswarm"
    assert "uptime_seconds" in data
    assert "checks" in data
    assert data["checks"]["database"] == "connected"


# ── Projects ─────────────────────────────────────────────────────────


def test_projects_page_loads(server, page: Page):
    page.goto(f"{BASE_URL}/projects/")
    # May have projects from prior runs — just verify the page loads
    assert page.title()


def test_add_project_form(server, page: Page):
    page.goto(f"{BASE_URL}/projects/new")
    expect(page.get_by_role("heading", name="Add Project")).to_be_visible()


def test_create_project_flow(server, page: Page):
    import uuid
    project_id = f"e2e-{uuid.uuid4().hex[:8]}"
    page.goto(f"{BASE_URL}/projects/new")
    page.fill('input[name="project_id"]', project_id)
    page.fill('input[name="repo"]', f"owner/{project_id}")
    page.click('button[type="submit"]')
    page.wait_for_url("**/projects/**")
    expect(page.locator(f"h3:has-text('{project_id}')")).to_be_visible()


# ── Cycles ───────────────────────────────────────────────────────────


def test_cycles_page_loads(server, page: Page):
    page.goto(f"{BASE_URL}/cycles/")
    expect(page.locator("text=No cycles")).to_be_visible()


# ── Reports ──────────────────────────────────────────────────────────


def test_reports_page_loads(server, page: Page):
    page.goto(f"{BASE_URL}/reports/")
    assert page.url.endswith("/reports/")


# ── API endpoints ────────────────────────────────────────────────────


def test_api_projects(server, page: Page):
    response = page.request.get(f"{BASE_URL}/api/projects")
    assert response.ok
    assert isinstance(response.json(), list)


def test_api_dashboard(server, page: Page):
    response = page.request.get(f"{BASE_URL}/api/dashboard")
    assert response.ok
    data = response.json()
    assert "active_cycles" in data
    assert "total_cost_today" in data


def test_api_live_state(server, page: Page):
    response = page.request.get(f"{BASE_URL}/api/live/state")
    assert response.ok
    data = response.json()
    assert "cycle_running" in data
    assert "cost_so_far" in data
    assert "recent_events" in data


def test_api_cycles(server, page: Page):
    response = page.request.get(f"{BASE_URL}/api/cycles")
    assert response.ok
    data = response.json()
    assert "cycles" in data


# ── Legacy routes should 404 ────────────────────────────────────────


def test_legacy_dashboard_gone(server, page: Page):
    response = page.request.get(f"{BASE_URL}/swarm/dashboard")
    assert response.status == 404


def test_legacy_reports_gone(server, page: Page):
    response = page.request.get(f"{BASE_URL}/swarm/reports/2026-01-01")
    assert response.status == 404
