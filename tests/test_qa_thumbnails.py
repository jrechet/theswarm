"""F4 — generate_demo_report threads thumbnails + GIF previews per video."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from theswarm.agents import qa as qa_module
from theswarm.agents.qa import generate_demo_report
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType


def _video_artifact(label: str, payload: bytes = b"WEBM_BYTES") -> tuple[Artifact, bytes]:
    return (
        Artifact(
            type=ArtifactType.VIDEO,
            label=label,
            path="",
            mime_type="video/webm",
            size_bytes=len(payload),
            created_at=datetime.now(timezone.utc),
        ),
        payload,
    )


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    from theswarm.infrastructure.recording import artifact_store

    orig = artifact_store.LocalArtifactStore.__init__

    def _init(self, base_dir: str = "") -> None:
        orig(self, str(tmp_path))

    monkeypatch.setattr(
        artifact_store.LocalArtifactStore,
        "__init__",
        _init,
    )
    return tmp_path


async def test_generate_demo_report_calls_thumbnailer_for_story_videos(
    isolated_store: Path, monkeypatch,
):
    thumb_calls: list[Path] = []
    gif_calls: list[Path] = []

    async def fake_thumb(video_path, out_path, at_seconds: float = 1.0):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
        thumb_calls.append(Path(video_path))
        return out_path

    async def fake_gif(video_path, out_path, max_seconds: float = 8.0, **_kw):
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"GIF89a" + b"\x00" * 32)
        gif_calls.append(Path(video_path))
        return out_path

    monkeypatch.setattr(qa_module, "make_thumbnail", fake_thumb, raising=False)
    monkeypatch.setattr(qa_module, "make_gif", fake_gif, raising=False)
    # Also patch at the import site (the function imports at call-time)
    from theswarm.infrastructure.recording import thumbnailer
    monkeypatch.setattr(thumbnailer, "make_thumbnail", fake_thumb)
    monkeypatch.setattr(thumbnailer, "make_gif", fake_gif)

    state = {
        "tests_passed": True,
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "e2e_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "issue_stats": {"open": 0, "closed_today": 1},
        "security_scan": {
            "semgrep_high": 0,
            "semgrep_status": "pass",
            "coverage_pct": 82.0,
            "coverage_status": "pass",
        },
        "demo_artifacts": [],
        "video_artifacts": [_video_artifact("cycle_walkthrough")],
        "story_artifacts": {},
        "story_videos": {
            42: _video_artifact("pr_42_walkthrough"),
            43: _video_artifact("pr_43_walkthrough"),
        },
    }

    result = await generate_demo_report(state)

    report = result["demo_report"]
    assert "thumbnails" in report
    assert "previews" in report
    assert "thumbnail_path" in report

    # 1 cycle-wide + 2 per-story videos = 3 thumbnails + 3 gifs
    assert len(report["thumbnails"]) == 3
    assert len(report["previews"]) == 3
    assert len(thumb_calls) == 3
    assert len(gif_calls) == 3

    # thumbnail_path is set and relative (not absolute)
    assert report["thumbnail_path"]
    assert not report["thumbnail_path"].startswith("/")
    assert report["thumbnail_path"].endswith(".jpg")


async def test_generate_demo_report_survives_thumbnailer_errors(
    isolated_store: Path, monkeypatch,
):
    from theswarm.infrastructure.recording import thumbnailer

    async def boom_thumb(*_a, **_kw):
        raise thumbnailer.ThumbnailError("ffmpeg blew up")

    async def boom_gif(*_a, **_kw):
        raise thumbnailer.ThumbnailError("ffmpeg blew up")

    monkeypatch.setattr(thumbnailer, "make_thumbnail", boom_thumb)
    monkeypatch.setattr(thumbnailer, "make_gif", boom_gif)

    state = {
        "tests_passed": True,
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "e2e_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "issue_stats": {"open": 0, "closed_today": 0},
        "security_scan": {
            "semgrep_high": 0,
            "semgrep_status": "pass",
            "coverage_pct": 80.0,
            "coverage_status": "pass",
        },
        "demo_artifacts": [],
        "video_artifacts": [_video_artifact("cycle_walkthrough")],
        "story_artifacts": {},
        "story_videos": {},
    }

    result = await generate_demo_report(state)
    report = result["demo_report"]

    # No thumbnails generated, but report still builds, and thumbnail_path is
    # an empty string (no fallback screenshots either).
    assert report["thumbnails"] == []
    assert report["previews"] == []
    assert report["thumbnail_path"] == ""


async def test_generate_demo_report_falls_back_to_screenshot_when_no_thumbnail(
    isolated_store: Path, monkeypatch,
):
    """When no videos exist but screenshots do, thumbnail_path uses first screenshot."""
    state = {
        "tests_passed": True,
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "e2e_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1},
        "issue_stats": {"open": 0, "closed_today": 0},
        "security_scan": {
            "semgrep_high": 0,
            "semgrep_status": "pass",
            "coverage_pct": 80.0,
            "coverage_status": "pass",
        },
        "demo_artifacts": [
            (
                Artifact(
                    type=ArtifactType.SCREENSHOT,
                    label="home",
                    path="",
                    mime_type="image/png",
                    size_bytes=16,
                    created_at=datetime.now(timezone.utc),
                ),
                b"\x89PNG\r\n\x1a\n" + b"\x00" * 8,
            ),
        ],
        "video_artifacts": [],
        "story_artifacts": {},
        "story_videos": {},
    }

    result = await generate_demo_report(state)
    report = result["demo_report"]

    assert report["thumbnails"] == []
    assert report["thumbnail_path"].endswith(".png")
    assert report["thumbnail_path"] == report["screenshots"][0]["path"]
