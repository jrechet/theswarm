"""The second capture lane launches once the first demo server answered.

Two servers booting side by side on a new database file race on the
target's first-boot DDL: on concert-tour-app one lane died on "table tours
already exists" and took its captures with it (2026-09-28). In a cycle,
QA's E2E run usually starts the target first — but not when the E2E file
could not be written (#147), and then the workspace's first boot is the
captures'. The video lane now waits for the screenshot lane's server to
answer, or for that lane to end, and the two walks still run side by side.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from theswarm.agents import qa


def _lanes(monkeypatch, order: list[str], *, shots_signal: bool = True):
    async def shots(state):
        order.append("shots-start")
        await asyncio.sleep(0.05)
        if shots_signal:
            state["demo_server_ready"].set()
        order.append("shots-ready")
        await asyncio.sleep(0.1)
        order.append("shots-end")
        return {"demo_artifacts": [], "tokens_used": 0}

    async def video(state):
        order.append("video-start")
        await asyncio.sleep(0.05)
        order.append("video-end")
        return {"video_artifacts": [], "tokens_used": 0}

    async def nothing(state):
        return {"tokens_used": 0}

    monkeypatch.setattr(qa, "capture_demo_screenshots", shots)
    monkeypatch.setattr(qa, "record_demo_video", video)
    monkeypatch.setattr(qa, "capture_before_after_per_story", nothing)
    monkeypatch.setattr(qa, "record_story_video", nothing)
    monkeypatch.setattr(qa, "_capture_concurrency", lambda: 2)


async def test_the_video_lane_launches_after_the_first_server_answered(monkeypatch):
    order: list[str] = []
    _lanes(monkeypatch, order)

    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock(return_value=[])):
        await qa.run_captures({"workspace": "/ws"})

    assert order.index("video-start") > order.index("shots-ready")
    assert order.index("video-start") < order.index("shots-end")  # still side by side


async def test_a_screenshot_lane_that_never_signals_does_not_hold_the_video(monkeypatch):
    order: list[str] = []
    _lanes(monkeypatch, order, shots_signal=False)

    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock(return_value=[])):
        await asyncio.wait_for(qa.run_captures({"workspace": "/ws"}), timeout=5)

    assert order.index("video-start") > order.index("shots-end")


async def test_the_screenshot_walk_signals_once_its_server_answers(monkeypatch, tmp_path):
    ready = asyncio.Event()
    seen: list[bool] = []

    class Recorder:
        async def screenshot(self, url, label):
            seen.append(ready.is_set())
            return (label, b"png")

        async def close(self):
            pass

    class Proc:
        returncode = None

        def send_signal(self, sig):
            self.returncode = 0

        async def wait(self):
            return 0

    monkeypatch.setattr(qa, "_page_status", AsyncMock(return_value=200))
    monkeypatch.setattr(qa, "e2e_port", lambda: 9998)
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [("", "homepage")])
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        await qa.capture_demo_screenshots(
            {"workspace": str(tmp_path), "claude": object(), "demo_server_ready": ready},
        )

    assert seen == [True]
