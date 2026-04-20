"""F2 — QA node: capture_before_after_per_story."""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.agents.qa import capture_before_after_per_story
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType
from theswarm.infrastructure.recording.playwright_recorder import PlaywrightRecorder


def _make_artifact(label: str) -> tuple[Artifact, bytes]:
    data = f"PNG:{label}".encode()
    return (
        Artifact(
            type=ArtifactType.SCREENSHOT,
            label=label,
            path="",
            mime_type="image/png",
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
        ),
        data,
    )


async def test_node_is_stub_without_workspace():
    result = await capture_before_after_per_story({"workspace": None})
    assert result["tokens_used"] == 0
    assert not result.get("story_artifacts")


async def test_node_noop_when_no_merged_prs():
    state = {"workspace": "/tmp/x", "merged_prs": [], "story_preview_urls": {}}
    result = await capture_before_after_per_story(state)
    assert result["story_artifacts"] == {}


async def test_node_noop_when_no_preview_urls():
    state = {"workspace": "/tmp/x", "merged_prs": [42], "story_preview_urls": {}}
    result = await capture_before_after_per_story(state)
    assert result["story_artifacts"] == {}


async def test_node_captures_before_and_after_for_configured_pr(monkeypatch):
    calls: list[tuple[str | None, str, str]] = []

    async def fake_cba(self, before_url, after_url, label):
        calls.append((before_url, after_url, label))
        out = []
        if before_url:
            out.append(_make_artifact(f"{label}_before"))
        out.append(_make_artifact(f"{label}_after"))
        return out

    async def fake_close(self):
        return None

    monkeypatch.setattr(PlaywrightRecorder, "capture_before_after", fake_cba)
    monkeypatch.setattr(PlaywrightRecorder, "close", fake_close)

    state = {
        "workspace": "/tmp/x",
        "merged_prs": [42, 43],
        "story_preview_urls": {
            42: {"before": "http://main/", "after": "http://pr-42/"},
            43: {"before": None, "after": "http://pr-43/"},
        },
    }

    result = await capture_before_after_per_story(state)

    assert set(result["story_artifacts"].keys()) == {42, 43}
    assert len(result["story_artifacts"][42]["before"]) == 1
    assert len(result["story_artifacts"][42]["after"]) == 1
    assert len(result["story_artifacts"][43]["before"]) == 0
    assert len(result["story_artifacts"][43]["after"]) == 1
    assert calls == [
        ("http://main/", "http://pr-42/", "pr_42"),
        (None, "http://pr-43/", "pr_43"),
    ]


async def test_node_skips_pr_missing_after_url(monkeypatch):
    async def fake_cba(self, before_url, after_url, label):
        return [_make_artifact(f"{label}_after")]

    async def fake_close(self):
        return None

    monkeypatch.setattr(PlaywrightRecorder, "capture_before_after", fake_cba)
    monkeypatch.setattr(PlaywrightRecorder, "close", fake_close)

    state = {
        "workspace": "/tmp/x",
        "merged_prs": [42, 99],
        "story_preview_urls": {
            42: {"before": None, "after": "http://pr-42/"},
            99: {"before": "http://main/", "after": None},
        },
    }

    result = await capture_before_after_per_story(state)
    assert set(result["story_artifacts"].keys()) == {42}


async def test_node_swallows_capture_errors(monkeypatch):
    async def fake_cba(self, before_url, after_url, label):
        if "42" in label:
            raise RuntimeError("playwright blew up")
        return [_make_artifact(f"{label}_after")]

    async def fake_close(self):
        return None

    monkeypatch.setattr(PlaywrightRecorder, "capture_before_after", fake_cba)
    monkeypatch.setattr(PlaywrightRecorder, "close", fake_close)

    state = {
        "workspace": "/tmp/x",
        "merged_prs": [42, 43],
        "story_preview_urls": {
            42: {"before": None, "after": "http://pr-42/"},
            43: {"before": None, "after": "http://pr-43/"},
        },
    }

    result = await capture_before_after_per_story(state)
    assert set(result["story_artifacts"].keys()) == {43}
