"""The E2E smoke walk CI requires (V3, M7): every page of the one product
answers without a server error, and axe finds no serious or critical
accessibility violation on the pages a person reads.

It boots the unified server on an isolated database with the wall down
(the way `theswarm serve` runs in a fresh checkout), walks the URLs of the
plan's table (docs/plans/2026-10-v3-one-product.md) and the API the
harness relies on, then runs axe-core (`axe-playwright-python`) on the
HTML pages. V1's walk went with V1 (M6).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page

SERVER_PORT = 8093
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"
ROOT = Path(__file__).resolve().parents[2]

# What a person reads: walked by the browser, audited by axe.
PAGES = [
    "/", "/login", "/c/internal", "/requests", "/settings/customers", "/settings/instance",
    "/health/ready/page", "/setup/github-oauth", "/setup/github-app",
]
# What a client reads: no 5xx, whatever the answer.
ENDPOINTS = [
    "/health", "/health/ready", "/api/health", "/api/dashboard", "/api/projects", "/api/cycles",
    "/api/features", "/api/live/state", "/api/devops", "/metrics", "/d/0123456789", "/dashboard",
]
AXE_IMPACTS = ("serious", "critical")


def _alive() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=2) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def server():
    """The unified server on an isolated database, the wall down, no self-seed."""
    tmp = tempfile.mkdtemp(prefix="theswarm-smoke-")
    env = {**os.environ, "SWARM_AUTH_DISABLED": "1", "SWARM_SKIP_SELF_SEED": "1", "SWARM_SKIP_DOTENV": "1",
           "SWARM_STACK_FILE": "/nonexistent/theswarm.yaml", "BASE_PATH": "", "PYTHONPATH": str(ROOT / "src")}
    env.pop("ANTHROPIC_API_KEY", None)
    log = open(Path(tmp) / "server.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "theswarm", "serve", "--host", "127.0.0.1", "--port", str(SERVER_PORT),
         "--db", str(Path(tmp) / "smoke.db")],
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(120):
        if _alive():
            break
        if proc.poll() is not None:
            raise RuntimeError(f"the server exited: {(Path(tmp) / 'server.log').read_text()[-2000:]}")
        time.sleep(1)
    else:
        proc.terminate()
        raise RuntimeError("the server did not answer /health in two minutes")
    yield BASE_URL
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


class TestRouteSmokeWalk:
    def test_every_page_and_endpoint_answers_without_a_server_error(self, server, page: Page):
        failures = []
        for route in PAGES + ENDPOINTS:
            resp = page.request.get(f"{server}{route}", headers={"accept": "text/html" if route in PAGES else "application/json"})
            if resp.status >= 500:
                failures.append(f"{route} -> {resp.status}")
        assert not failures, f"routes answering 5xx: {failures}"

    def test_v1_addresses_are_gone(self, server, page: Page):
        for route in ("/dashboard", "/projects/", "/cycles/", "/demos/", "/team", "/reports/"):
            resp = page.request.get(f"{server}{route}", headers={"accept": "text/html"})
            assert resp.status == 404, f"{route} answered {resp.status}"

    def test_the_pages_pass_axe(self, server, page: Page):
        """No serious or critical violation on any page a person reads (M7)."""
        from axe_playwright_python.sync_playwright import Axe

        axe = Axe()
        findings = []
        for route in PAGES:
            page.goto(f"{server}{route}", wait_until="domcontentloaded")
            results = axe.run(page)
            for violation in results.response.get("violations", []):
                if violation.get("impact") in AXE_IMPACTS:
                    targets = [n.get("target") for n in violation.get("nodes", [])][:3]
                    findings.append(f"{route}: {violation['id']} ({violation['impact']}) — {violation.get('help')} at {targets}")
        assert not findings, "axe violations:\n" + "\n".join(findings)
