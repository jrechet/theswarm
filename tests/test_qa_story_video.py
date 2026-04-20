"""F3 — QA node: record_story_video."""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.agents.qa import record_story_video
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType
from theswarm.infrastructure.recording.playwright_recorder import PlaywrightRecorder


def _make_video_artifact(label: str) -> tuple[Artifact, bytes]:
    data = f"WEBM:{label}".encode() * 10  # non-zero webm-ish payload
    return (
        Artifact(
            type=ArtifactType.VIDEO,
            label=label,
            path="",
            mime_type="video/webm",
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
        ),
        data,
    )


class _FakePage:
    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    class _Mouse:
        async def wheel(self, _dx: int, _dy: int) -> None:
            return None

    mouse = _Mouse()


async def test_node_is_stub_without_workspace():
    result = await record_story_video({"workspace": None})
    assert result["tokens_used"] == 0
    assert not result.get("story_videos")


async def test_node_noop_when_no_merged_prs():
    state = {"workspace": "/tmp/x", "merged_prs": [], "story_preview_urls": {}}
    result = await record_story_video(state)
    assert result["story_videos"] == {}


async def test_node_records_per_pr_walkthroughs(monkeypatch):
    started: list[str] = []

    async def fake_start(self, url):
        started.append(url)
        self._recording_page = _FakePage()

    stop_calls: list[int] = []

    async def fake_stop(self):
        stop_calls.append(1)
        return _make_video_artifact(f"raw_{len(stop_calls)}")

    async def fake_close(self):
        return None

    monkeypatch.setattr(PlaywrightRecorder, "start_recording", fake_start)
    monkeypatch.setattr(PlaywrightRecorder, "stop_recording", fake_stop)
    monkeypatch.setattr(PlaywrightRecorder, "close", fake_close)

    state = {
        "workspace": "/tmp/x",
        "merged_prs": [42, 43, 99],
        "story_preview_urls": {
            42: {"before": None, "after": "http://pr-42/"},
            43: {"before": "http://main/", "after": "http://pr-43/"},
            99: {"before": None, "after": None},  # skipped
        },
    }

    result = await record_story_video(state)

    videos = result["story_videos"]
    assert set(videos.keys()) == {42, 43}
    assert videos[42][0].label == "pr_42_walkthrough"
    assert videos[43][0].label == "pr_43_walkthrough"
    assert videos[42][0].type == ArtifactType.VIDEO
    assert videos[42][0].size_bytes == len(videos[42][1])
    assert started == ["http://pr-42/", "http://pr-43/"]


async def test_node_swallows_per_pr_failures(monkeypatch):
    async def fake_start(self, url):
        if "42" in url:
            raise RuntimeError("playwright blew up")
        self._recording_page = _FakePage()

    async def fake_stop(self):
        return _make_video_artifact("raw")

    async def fake_close(self):
        return None

    monkeypatch.setattr(PlaywrightRecorder, "start_recording", fake_start)
    monkeypatch.setattr(PlaywrightRecorder, "stop_recording", fake_stop)
    monkeypatch.setattr(PlaywrightRecorder, "close", fake_close)

    state = {
        "workspace": "/tmp/x",
        "merged_prs": [42, 43],
        "story_preview_urls": {
            42: {"before": None, "after": "http://pr-42/"},
            43: {"before": None, "after": "http://pr-43/"},
        },
    }

    result = await record_story_video(state)
    assert set(result["story_videos"].keys()) == {43}
