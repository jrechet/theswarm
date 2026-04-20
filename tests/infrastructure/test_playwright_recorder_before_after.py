"""F2 — PlaywrightRecorder.capture_before_after."""

from __future__ import annotations

import logging

import pytest

from theswarm.domain.reporting.value_objects import ArtifactType
from theswarm.infrastructure.recording.playwright_recorder import PlaywrightRecorder


@pytest.fixture
def recorder():
    return PlaywrightRecorder()


async def _fake_screenshot(_self, url: str, label: str):
    from datetime import datetime, timezone

    from theswarm.domain.reporting.value_objects import Artifact

    data = f"PNG:{url}:{label}".encode()
    artifact = Artifact(
        type=ArtifactType.SCREENSHOT,
        label=label,
        path="",
        mime_type="image/png",
        size_bytes=len(data),
        created_at=datetime.now(timezone.utc),
    )
    return artifact, data


async def test_capture_before_after_returns_both_when_before_url_given(
    recorder, monkeypatch,
):
    monkeypatch.setattr(PlaywrightRecorder, "screenshot", _fake_screenshot)

    results = await recorder.capture_before_after(
        before_url="http://main.example.com",
        after_url="http://pr-42.example.com",
        label="story_42",
    )

    assert len(results) == 2
    before_artifact, before_bytes = results[0]
    after_artifact, after_bytes = results[1]

    assert before_artifact.label == "story_42_before"
    assert after_artifact.label == "story_42_after"
    assert before_artifact.type == ArtifactType.SCREENSHOT
    assert after_artifact.type == ArtifactType.SCREENSHOT
    assert b"main.example.com" in before_bytes
    assert b"pr-42.example.com" in after_bytes


async def test_capture_before_after_skips_before_when_url_none(
    recorder, monkeypatch, caplog,
):
    monkeypatch.setattr(PlaywrightRecorder, "screenshot", _fake_screenshot)

    with caplog.at_level(logging.WARNING):
        results = await recorder.capture_before_after(
            before_url=None,
            after_url="http://pr-42.example.com",
            label="story_42",
        )

    assert len(results) == 1
    assert results[0][0].label == "story_42_after"
    assert any("story_42" in r.message for r in caplog.records)


async def test_capture_before_after_skips_before_when_url_empty(
    recorder, monkeypatch,
):
    monkeypatch.setattr(PlaywrightRecorder, "screenshot", _fake_screenshot)

    results = await recorder.capture_before_after(
        before_url="",
        after_url="http://pr-42.example.com",
        label="story_42",
    )

    assert len(results) == 1
    assert results[0][0].label == "story_42_after"


async def test_capture_before_after_delegates_to_screenshot(recorder):
    import types

    calls: list[tuple[str, str]] = []

    async def record(_self, url: str, label: str):
        calls.append((url, label))
        return await _fake_screenshot(_self, url, label)

    recorder.screenshot = types.MethodType(record, recorder)

    await recorder.capture_before_after(
        before_url="http://main/",
        after_url="http://branch/",
        label="s1",
    )

    assert calls == [("http://main/", "s1_before"), ("http://branch/", "s1_after")]
