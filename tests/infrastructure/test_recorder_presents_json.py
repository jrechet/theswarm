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


# ── Legible at the size of the demo card (2026-09-30) ────────────────
# The theater's demo card plays the video about 256 px wide: a cream page of
# 20 px text read as a blank frame there (reschedule-concert, tour-span).
# The request line is a band in its status's atelier colour, large.

MOSS = "rgb(63, 122, 70)"  # the atelier moss: an answer


async def band_of(page) -> tuple[str, float, float]:
    """(background colour, font size, width) of the drawn request line."""
    return tuple(await page.locator("header").evaluate(
        "h => { const s = getComputedStyle(h);"
        " return [s.backgroundColor, parseFloat(s.fontSize), h.getBoundingClientRect().width]; }"))


async def test_a_json_page_s_request_line_is_a_band_in_its_status_colour(page):
    await page.set_viewport_size({"width": 1280, "height": 720})
    await page.goto("http://demo.test/api/v1/concerts/1/occupancy")

    await present_json(page, "/api/v1/concerts/1/occupancy", 200)

    colour, size, width = await band_of(page)
    assert colour == MOSS and size >= 28 and width == 1280
    assert await page.locator("header").inner_text() == "GET /api/v1/concerts/1/occupancy → 200"
