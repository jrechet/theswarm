"""A POST feature's demo shows the feature: its own requests, played.

sell-tickets (cycle 68fd55bf81e5, 2026-09-29) added one route,
`POST /api/v1/concerts/{concert_id}/tickets`. The demo walked GET pages
only — "a POST needs a body nobody can invent" — so its video was four
seconds of the API root and its screenshots the dashboard, and the
`feature_pages` gate said "not run". Its tests passed; nobody could *see*
a ticket being sold.

One Claude call reads the workspace and writes a short script against the
seeded demo data — what the data looks like, the feature's own request with
a real body, what changed. QA plays it on each lane's own demo server (a
database of its own, thrown away after), draws every exchange legibly in
the screenshots and the video, and what the feature's own calls answered is
the `feature_calls` gate: 5xx fails, 2xx passes, a 4xx proves nothing (the
body was written blind).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from theswarm import evals
from theswarm.agents import qa
from theswarm.agents import qa_feature_calls as fc
from theswarm.agents import qa_feature_pages as fp

CONCERTS = '''from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/concerts", tags=["concerts"])


@router.get("/{concert_id}")
def get_concert(concert_id: int):
    return find(concert_id)


@router.post("/{concert_id}/tickets", status_code=201)
def sell_tickets(concert_id: int, payload: TicketPurchase):
    return sell(concert_id, payload)
'''

ADDS_TICKETS = '''@@ -8,3 +8,8 @@ def get_concert(concert_id: int):
     return find(concert_id)


+@router.post("/{concert_id}/tickets", status_code=201)
+def sell_tickets(concert_id: int, payload: TicketPurchase):
+    return sell(concert_id, payload)
'''

ROUTE = {"pr": 449, "method": "POST", "path": "/api/v1/concerts/{concert_id}/tickets"}
CALLS = [
    {"method": "GET", "path": "/api/v1/concerts/1", "json_body": None,
     "caption": "Before: 120 of 500 tickets sold"},
    {"method": "POST", "path": "/api/v1/concerts/1/tickets", "json_body": {"quantity": 2},
     "caption": "Sell two tickets"},
    {"method": "GET", "path": "/api/v1/concerts/1", "json_body": None,
     "caption": "After: 122 sold"},
]


# ── Which routes the feature added ───────────────────────────────────


def test_every_touched_route_is_read_with_its_method_and_template():
    assert fp.touched_routes(ADDS_TICKETS, CONCERTS) == [
        ("post", "/api/v1/concerts/{concert_id}/tickets")]
    assert fp.touched_get_paths(ADDS_TICKETS, CONCERTS) == []  # the GET walk is unchanged


async def test_the_feature_s_routes_are_its_non_get_ones_per_pr():
    github = AsyncMock()
    github.get_pr_files = AsyncMock(return_value=[
        {"filename": "src/routers/concerts.py", "patch": ADDS_TICKETS}])
    github.get_file_content = AsyncMock(return_value=CONCERTS)

    routes = await fc.feature_routes(github, [{"number": 449, "head_sha": "abc"}])

    assert routes == [ROUTE]


# ── The script ───────────────────────────────────────────────────────


def _claude(calls):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        structured={"calls": calls}, text="", total_tokens=50, cost_usd=0.04))
    return claude


async def test_one_call_writes_the_script_from_the_code_and_the_seed(tmp_path):
    claude = _claude(CALLS)

    script = await fc.write_demo_calls(claude, str(tmp_path), [ROUTE], seed="- `python scripts/seed_demo.py`")

    assert [c["method"] for c in script["calls"]] == ["GET", "POST", "GET"]
    assert script["routes"] == [ROUTE] and script["reason"] == ""
    prompt = claude.run.await_args.args[0]
    assert "POST /api/v1/concerts/{concert_id}/tickets (PR #449)" in prompt
    assert "scripts/seed_demo.py" in prompt
    kwargs = claude.run.await_args.kwargs
    assert kwargs["workdir"] == str(tmp_path) and kwargs["output_schema"]


@pytest.mark.parametrize("path", ["http://evil.example/x", "//evil.example/x", "api/v1/x", "/a\n/b", ""])
async def test_a_call_that_leaves_the_demo_server_is_dropped(tmp_path, path):
    bad = {"method": "POST", "path": path, "json_body": {}, "caption": "?"}

    script = await fc.write_demo_calls(_claude([bad, CALLS[1]]), str(tmp_path), [ROUTE])

    assert [c["path"] for c in script["calls"]] == ["/api/v1/concerts/1/tickets"]


async def test_the_script_is_short(tmp_path):
    script = await fc.write_demo_calls(_claude(CALLS * 4), str(tmp_path), [ROUTE])

    assert len(script["calls"]) == fc.MAX_DEMO_CALLS


async def test_no_route_but_get_means_no_call(tmp_path):
    claude = _claude(CALLS)

    script = await fc.write_demo_calls(claude, str(tmp_path), [])

    claude.run.assert_not_awaited()
    assert script == {"routes": [], "calls": [], "reason": ""}


async def test_a_script_that_cannot_be_written_says_why(tmp_path):
    claude = MagicMock()
    claude.run = AsyncMock(side_effect=RuntimeError("timeout after 240s"))

    script = await fc.write_demo_calls(claude, str(tmp_path), [ROUTE])

    assert script["calls"] == [] and "timeout after 240s" in script["reason"]


def test_the_feature_s_own_calls_are_labelled_as_its_pr_s_story():
    labelled = fc.label_calls(CALLS, [ROUTE])

    assert [c["label"] for c in labelled] == [
        "feature_call_1_concerts_1",
        "feature_pr_449_post_concerts_1_tickets",
        "feature_call_3_concerts_1",
    ]
    assert fp.pr_of_label(labelled[1]["label"]) == 449
    assert fp.pr_of_label(labelled[0]["label"]) is None


# ── Playing it ───────────────────────────────────────────────────────


@respx.mock
async def test_the_calls_are_played_in_order_on_the_demo_server():
    respx.get("http://127.0.0.1:9101/api/v1/concerts/1").mock(side_effect=[
        httpx.Response(200, json={"id": 1, "tickets_sold": 120}),
        httpx.Response(200, json={"id": 1, "tickets_sold": 122}),
    ])
    sold = respx.post("http://127.0.0.1:9101/api/v1/concerts/1/tickets").mock(
        return_value=httpx.Response(201, json={"concert_id": 1, "quantity": 2}))

    results = await fc.play_calls("http://127.0.0.1:9101", fc.label_calls(CALLS, [ROUTE]))

    assert [r["status"] for r in results] == [200, 201, 200]
    assert json.loads(sold.calls.last.request.content) == {"quantity": 2}
    assert '"tickets_sold":122' in results[2]["body"].replace(" ", "")
    assert results[1]["label"] == "feature_pr_449_post_concerts_1_tickets"
    assert results[1]["content_type"].startswith("application/json")


@respx.mock
async def test_a_call_that_gets_no_answer_is_recorded_as_such():
    respx.post("http://127.0.0.1:9101/api/v1/concerts/1/tickets").mock(
        side_effect=httpx.ConnectError("refused"))

    (result,) = await fc.play_calls("http://127.0.0.1:9101", fc.label_calls([CALLS[1]], [ROUTE]))

    assert result["status"] is None and "refused" in result["body"]


# ── The gate ─────────────────────────────────────────────────────────


def _result(label, status, method="POST", path="/api/v1/concerts/1/tickets"):
    return {"label": label, "method": method, "path": path, "status": status}


OWN = "feature_pr_449_post_concerts_1_tickets"


@pytest.mark.parametrize("results,status,reason", [
    ([_result("feature_call_1_concerts_1", 200, "GET", "/api/v1/concerts/1"), _result(OWN, 201)],
     "pass", "1 of 1 call(s) of the feature answered 2xx"),
    ([_result(OWN, 500)], "fail", "POST /api/v1/concerts/1/tickets answered 500"),
    ([_result(OWN, 422)], "not_run", "no call of the feature answered 2xx: POST /api/v1/concerts/1/tickets 422"),
    ([_result("feature_call_1_concerts_1", 500, "GET", "/api/v1/concerts/1"), _result(OWN, 201)],
     "pass", "1 of 1 call(s) of the feature answered 2xx"),  # only the feature's own calls judge
])
def test_what_the_feature_s_own_calls_answered_is_the_verdict(results, status, reason):
    gate = fc.feature_calls_gate({"routes": [ROUTE], "calls": CALLS, "reason": ""}, results)

    assert gate["status"] == status and gate["reason"] == reason


def test_no_route_touched_is_not_run():
    gate = fc.feature_calls_gate({"routes": [], "calls": [], "reason": ""}, [])

    assert gate == {"status": "not_run", "calls": [], "reason": "the PRs touch no route"}


def test_get_routes_that_walk_as_is_need_no_call():
    get_route = {"pr": 470, "method": "GET", "path": "/api/v1/concerts/sold-out"}

    gate = fc.feature_calls_gate({"routes": [get_route], "calls": [], "reason": ""}, [])

    assert gate["status"] == "not_run" and gate["reason"] == "the pages are the demo — every route walks as is"


def test_a_script_nobody_could_write_is_not_run_with_its_reason():
    gate = fc.feature_calls_gate({"routes": [ROUTE], "calls": [], "reason": "timeout after 240s"}, [])

    assert gate["status"] == "not_run" and "timeout after 240s" in gate["reason"]


def test_a_demo_server_that_never_started_is_not_run():
    gate = fc.feature_calls_gate({"routes": [ROUTE], "calls": CALLS, "reason": ""}, [],
                                 launch_error="No module named src")

    assert gate["status"] == "not_run" and "No module named src" in gate["reason"]


def test_the_gate_judges_the_behaviour():
    assert "feature_calls" in evals.QA_GATES and "feature_calls" in evals.BEHAVIOUR_GATES
    assert evals.behaviour_of({"feature_calls": "pass", "feature_pages": "not_run"}) == "verified"
    assert evals.behaviour_of({"feature_calls": "fail", "feature_e2e": "pass"}) == "broken"


def test_the_harness_names_it():
    import importlib.util
    import pathlib
    import sys

    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py"
    spec = importlib.util.spec_from_file_location("cycle_e2e_for_calls", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    notes = module.behaviour_notes({"quality_gates": {
        "feature_calls": {"status": "pass", "reason": "1 of 1 call(s) of the feature answered 2xx"}}})

    assert notes == ["feature calls pass: 1 of 1 call(s) of the feature answered 2xx"]


# ── Wired into QA ────────────────────────────────────────────────────


class _Proc:
    returncode = None

    def send_signal(self, sig):
        self.returncode = 0

    async def wait(self):
        return 0

    def kill(self):
        self.returncode = -9


def _lane_patches(monkeypatch, port):
    monkeypatch.setattr(qa, "run_seed", AsyncMock(return_value=[]))
    monkeypatch.setattr(qa, "e2e_port", lambda: port)
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [])


PLAYED = [dict(c, label=l, status=s, content_type="application/json", body="{}", request=c["json_body"])
          for c, l, s in zip(CALLS, ["feature_call_1_concerts_1", OWN, "feature_call_3_concerts_1"],
                             [200, 201, 200])]


async def test_the_screenshot_lane_plays_the_script_and_draws_each_exchange(tmp_path, monkeypatch):
    drawn: list[str] = []

    class Recorder:
        async def screenshot_exchange(self, exchange):
            drawn.append(exchange["label"])
            return (SimpleNamespace(label=exchange["label"]), b"png")

        async def close(self):
            pass

    played = AsyncMock(return_value=PLAYED)
    monkeypatch.setattr(fc, "play_calls", played)
    _lane_patches(monkeypatch, 9100)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        out = await qa.capture_demo_screenshots({
            "workspace": str(tmp_path), "claude": object(),
            "feature_calls": {"routes": [ROUTE], "calls": fc.label_calls(CALLS, [ROUTE]), "reason": ""},
        })

    assert played.await_args.args[0] == "http://127.0.0.1:9101"
    assert drawn == ["feature_call_1_concerts_1", OWN, "feature_call_3_concerts_1"]
    assert [r["status"] for r in out["feature_call_results"]] == [200, 201, 200]
    assert len(out["demo_artifacts"]) == 3


async def test_the_video_lane_plays_it_too(tmp_path, monkeypatch):
    shown: list[str] = []

    class Page:
        async def wait_for_timeout(self, ms):
            pass

    class Recorder:
        _recording_page = Page()

        async def start_recording(self, url):
            pass

        async def stop_recording(self):
            return SimpleNamespace(label="video"), b"webm"

        async def close(self):
            pass

    async def present(page, exchange):
        shown.append(exchange["label"])

    monkeypatch.setattr(fc, "play_calls", AsyncMock(return_value=PLAYED))
    _lane_patches(monkeypatch, 9100)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder), \
         patch("theswarm.infrastructure.recording.playwright_recorder.present_exchange", present):
        out = await qa.record_demo_video({
            "workspace": str(tmp_path), "claude": object(),
            "feature_calls": {"routes": [ROUTE], "calls": fc.label_calls(CALLS, [ROUTE]), "reason": ""},
        })

    assert shown == ["feature_call_1_concerts_1", OWN, "feature_call_3_concerts_1"]
    assert len(out["video_artifacts"]) == 1


async def test_the_script_is_written_once_for_both_lanes(monkeypatch):
    seen: list[dict] = []
    write = AsyncMock(return_value={"routes": [ROUTE], "calls": CALLS, "reason": ""})
    monkeypatch.setattr(fc, "feature_routes", AsyncMock(return_value=[ROUTE]))
    monkeypatch.setattr(fc, "write_demo_calls", write)

    async def lane(state):
        seen.append(state.get("feature_calls"))
        return {}

    monkeypatch.setattr(qa, "capture_demo_screenshots", lane)
    monkeypatch.setattr(qa, "capture_before_after_per_story", AsyncMock(return_value={}))
    monkeypatch.setattr(qa, "record_story_video", AsyncMock(return_value={}))
    monkeypatch.setattr(qa, "record_demo_video", lane)

    out = await qa.run_captures({"workspace": "/w", "claude": object(), "github": object(),
                                 "prs": [{"number": 449}], "feature_pages": []})

    write.assert_awaited_once()
    assert len(seen) == 2 and all(s["calls"] == CALLS for s in seen)
    assert out["feature_calls"]["calls"] == CALLS


async def test_the_report_carries_the_gate():
    from theswarm.application.services.report_generator import _qa_quality_gates
    from theswarm.domain.reporting.value_objects import QualityStatus

    state = {
        "feature_calls": {"routes": [ROUTE], "calls": CALLS, "reason": ""},
        "feature_call_results": [_result(OWN, 201)],
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "e2e_passed": True,
    }
    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=[])):
        out = await qa.generate_demo_report(state)

    gate = out["demo_report"]["quality_gates"]["feature_calls"]
    assert gate["status"] == "pass"
    (stored,) = [g for g in _qa_quality_gates(out["demo_report"]["quality_gates"])
                 if g.name == "feature_calls"]
    assert stored.status == QualityStatus.PASS


def test_the_state_declares_them():
    from theswarm.config import AgentState

    assert {"feature_calls", "feature_call_results"} <= set(AgentState.__annotations__)


# ── Drawn legible ────────────────────────────────────────────────────


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


async def test_an_exchange_is_drawn_as_request_and_answer(page):
    from theswarm.infrastructure.recording.playwright_recorder import present_exchange

    await present_exchange(page, {
        "method": "POST", "path": "/api/v1/concerts/1/tickets", "caption": "Sell two tickets",
        "request": {"quantity": 2}, "status": 201, "content_type": "application/json",
        "body": '{"concert_id": 1, "quantity": 2, "tickets_sold": 122}',
    })

    assert await page.locator("header").inner_text() == "POST /api/v1/concerts/1/tickets → 201"
    assert await page.locator("p.caption").inner_text() == "Sell two tickets"
    request, answer = await page.locator("pre").all_inner_texts()
    assert '"quantity": 2' in request
    assert '"tickets_sold": 122' in answer  # pretty-printed


async def test_an_answer_with_no_body_says_so(page):
    """A DELETE answers 204 with nothing: the answer box read blank."""
    from theswarm.infrastructure.recording.playwright_recorder import present_exchange

    await present_exchange(page, {
        "method": "DELETE", "path": "/api/v1/concerts/1/lineup/2", "caption": "Take the opening act off",
        "request": None, "status": 204, "content_type": "", "body": "",
    })

    assert await page.locator("header").inner_text() == "DELETE /api/v1/concerts/1/lineup/2 → 204"
    assert await page.locator("pre").all_inner_texts() == ["(empty)"]


# ── GET routes that need input (artist-search, da79522769b3) ─────────
# `/api/v1/tours/search` needs `?artist=`: the plain walk got a 422, the
# feature_pages gate said "not run" and the demo showed the dashboard.

SEARCH_ROUTE = {"pr": 505, "method": "GET", "path": "/api/v1/tours/search"}


async def test_get_routes_reach_the_writer():
    github = AsyncMock()
    patch_text = ADDS_TICKETS.replace('@router.post("/{concert_id}/tickets", status_code=201)',
                                      '@router.get("/{concert_id}/tickets/summary")')
    source = CONCERTS.replace('@router.post("/{concert_id}/tickets", status_code=201)',
                              '@router.get("/{concert_id}/tickets/summary")')
    github.get_pr_files = AsyncMock(return_value=[{"filename": "src/routers/concerts.py", "patch": patch_text}])
    github.get_file_content = AsyncMock(return_value=source)

    routes = await fc.feature_routes(github, [{"number": 505, "head_sha": "abc"}])

    assert routes == [{"pr": 505, "method": "GET", "path": "/api/v1/concerts/{concert_id}/tickets/summary"}]


async def test_the_writer_is_told_when_a_get_needs_a_call(tmp_path):
    claude = _claude([{"method": "GET", "path": "/api/v1/tours/search?artist=neon", "json_body": None,
                       "caption": "Tours whose artist contains \"neon\""}])

    script = await fc.write_demo_calls(claude, str(tmp_path), [SEARCH_ROUTE])

    prompt = claude.run.await_args.args[0]
    assert "needs no call" in prompt and "query parameters" in prompt
    (call,) = script["calls"]
    assert call["label"] == "feature_pr_505_get_tours_search_artist_neon"


def test_a_get_call_of_the_feature_judges_it():
    results = [{"label": "feature_pr_505_get_tours_search_artist_neon", "method": "GET",
                "path": "/api/v1/tours/search?artist=neon", "status": 200}]

    gate = fc.feature_calls_gate({"routes": [SEARCH_ROUTE], "calls": results, "reason": ""}, results)

    assert gate["status"] == "pass"
