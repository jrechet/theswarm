"""QA's E2E run meets the demo's data; a download is shown, not lost.

Cycle of 2026-09-29 (ical-feed): with a database of its own per demo
server (#256, concert-tour-app#425) the E2E server started empty — only
the capture lanes were seeded — and ten E2E tests of the feature asked for
tour 1: `calendar.ics` answered 404, the verdict read "broken", and the
swarm's own PO wrote "a test-data/seeding issue, not a broken feature".
The E2E server is seeded like the others, and the E2E prompt says so.

The same page, `text/calendar`, made Chromium start a download: no
screenshot, no frame in the video. A response that is neither a page nor
JSON is drawn as text.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.agents import qa
from theswarm.infrastructure.recording.playwright_recorder import present_text

DECLARED = """\
demo:
  command: "{python} -m uvicorn src.main:app --host 127.0.0.1 --port {port}"
  env:
    DATABASE_URL: "sqlite:///{tmp}/demo.db"
  seed:
    - "{python} scripts/seed_demo.py"
"""

ICS = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nSUMMARY:Aurora Belle — Nashville\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"


class _Proc:
    returncode = None

    def send_signal(self, sig):
        self.returncode = 0

    async def wait(self):
        return 0

    def kill(self):
        self.returncode = -9


async def test_the_e2e_server_is_seeded_like_the_demo_servers(tmp_path, monkeypatch):
    (tmp_path / "theswarm.yaml").write_text(DECLARED)
    seen: list[tuple] = []

    async def seed(workspace, commands, *, python, url, env):
        seen.append((url, env.get("DATABASE_URL", "")))
        return []

    monkeypatch.setattr(qa, "run_seed", seed)
    monkeypatch.setattr(qa, "e2e_port", lambda: 9100)
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()):
        _, error = await qa._start_e2e_server(str(tmp_path), "/venv/bin/python")

    assert error == ""
    ((url, database),) = seen
    assert url == "http://127.0.0.1:9100" and database.endswith("/demo.db")


def test_the_e2e_prompt_says_what_data_the_app_starts_with(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(DECLARED)

    section = qa._seed_section(str(tmp_path))

    assert "scripts/seed_demo.py" in section
    assert "ids" in section


def test_no_seed_declared_says_nothing(tmp_path):
    assert qa._seed_section(str(tmp_path)) == ""


# ── Downloads ────────────────────────────────────────────────────────


@pytest.mark.parametrize("content_type,shown_as_text", [
    ("text/calendar; charset=utf-8", True),
    ("text/csv", True),
    ("application/octet-stream", True),
    ("text/html; charset=utf-8", False),
    ("application/json", False),
    ("", False),
])
def test_what_is_drawn_as_text(content_type, shown_as_text):
    assert qa._is_download(content_type) is shown_as_text


async def test_the_screenshot_walk_draws_a_download_as_text(tmp_path, monkeypatch):
    drawn: list[tuple] = []

    class Recorder:
        async def screenshot(self, url, label):
            raise AssertionError("a download is not navigated to")

        async def screenshot_text(self, url, label, *, status, content_type, body):
            drawn.append((label, status, content_type, body))
            return (label, b"png")

        async def close(self):
            pass

    async def probe(url):
        return 200, "text/calendar; charset=utf-8", ICS

    monkeypatch.setattr(qa, "_probe_page", probe)
    monkeypatch.setattr(qa, "run_seed", AsyncMock(return_value=[]))
    monkeypatch.setattr(qa, "e2e_port", lambda: 9998)
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: list(extra))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        out = await qa.capture_demo_screenshots({
            "workspace": str(tmp_path), "claude": object(),
            "feature_pages": [("/api/v1/tours/1/calendar.ics", "feature_pr_431_tours_1_calendar_ics")],
        })

    assert drawn == [("feature_pr_431_tours_1_calendar_ics", 200, "text/calendar; charset=utf-8", ICS)]
    assert out["feature_page_statuses"] == {"/api/v1/tours/1/calendar.ics": 200}


@pytest.fixture()
async def page():
    pw_api = pytest.importorskip("playwright.async_api")
    playwright = await pw_api.async_playwright().start()
    try:
        browser = await playwright.chromium.launch()
    except Exception as exc:  # noqa: BLE001 — no browser on this runner
        await playwright.stop()
        pytest.skip(f"no Chromium here: {exc}")
    page = await browser.new_page()
    yield page
    await browser.close()
    await playwright.stop()


async def test_a_text_answer_is_drawn_legibly(page):
    await present_text(page, "/api/v1/tours/1/calendar.ics", 200, "text/calendar", ICS)

    assert await page.locator("header").inner_text() == "GET /api/v1/tours/1/calendar.ics → 200 · text/calendar"
    assert "SUMMARY:Aurora Belle — Nashville" in await page.locator("pre").inner_text()
