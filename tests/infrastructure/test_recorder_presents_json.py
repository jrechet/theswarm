"""An API page in a demo is legible (seen in docs/demos/qa-feature-pages.webm).

The pages a cycle's PRs add are often JSON: Chromium drew
{"concert_id":1,"tickets_sold":15000,...} in 13px on a white page, a line
nobody reads in a thumbnail or a video. The recorder redraws a JSON page
as the request and its answer, pretty-printed, large.
"""

from __future__ import annotations

import pytest

from theswarm.infrastructure.recording.playwright_recorder import present_json

BODY = '{"concert_id":1,"tickets_sold":15000,"capacity":20000,"percentage_sold":75.0}'


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
    await page.route("http://demo.test/**", lambda route: route.fulfill(
        status=200,
        content_type="application/json" if "api" in route.request.url else "text/html",
        body=BODY if "api" in route.request.url else "<h1>Dashboard</h1>",
    ))
    yield page
    await browser.close()
    await playwright.stop()


async def test_a_json_page_is_redrawn_as_the_request_and_its_answer(page):
    await page.goto("http://demo.test/api/v1/concerts/1/occupancy")

    assert await present_json(page, "/api/v1/concerts/1/occupancy", 200) is True

    assert await page.locator("header").inner_text() == "GET /api/v1/concerts/1/occupancy → 200"
    pretty = await page.locator("pre").inner_text()
    assert '"tickets_sold": 15000' in pretty and pretty.count("\n") >= 5


async def test_an_html_page_is_left_alone(page):
    await page.goto("http://demo.test/dashboard")

    assert await present_json(page, "/dashboard", 200) is False
    assert await page.locator("h1").inner_text() == "Dashboard"
