"""The video lane closes its browser when the recording works, not only when
it fails: every cycle left a Playwright driver and its Chromium alive in
prod's container — 1.1 GB of its 2 GB after three cycles (2026-10-11)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from theswarm.agents import qa


class _Recorder:
    made: list["_Recorder"] = []

    def __init__(self):
        self.closed = False
        self._recording_page = object()
        _Recorder.made.append(self)

    async def start_recording(self, url):
        pass

    async def stop_recording(self):
        return ("video", b"webm")

    async def close(self):
        self.closed = True


class _Proc:
    returncode = None

    def send_signal(self, sig):
        self.returncode = 0

    async def wait(self):
        return 0


async def test_a_recording_that_works_closes_its_browser(tmp_path, monkeypatch):
    _Recorder.made.clear()
    monkeypatch.setattr(qa, "run_seed", AsyncMock(return_value=[]))
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [])
    monkeypatch.setattr(qa, "_play_feature_calls", AsyncMock(return_value=[]))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", _Recorder):
        result = await qa.record_demo_video({"workspace": str(tmp_path), "claude": object()})

    assert result["video_artifacts"] == [("video", b"webm")]
    assert [r.closed for r in _Recorder.made] == [True]
