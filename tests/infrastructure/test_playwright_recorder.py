"""Tests for PlaywrightRecorder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.domain.reporting.value_objects import ArtifactType
from theswarm.infrastructure.recording.playwright_recorder import PlaywrightRecorder


@pytest.fixture
def recorder():
    return PlaywrightRecorder(viewport_width=800, viewport_height=600)


class TestScreenshot:
    async def test_screenshot_returns_artifact_and_bytes(self, recorder):
        """Screenshot returns an Artifact with type SCREENSHOT and PNG bytes."""
        fake_page = AsyncMock()
        fake_page.screenshot = AsyncMock(return_value=b"\x89PNG_FAKE_DATA")
        fake_page.wait_for_timeout = AsyncMock()
        fake_page.goto = AsyncMock()

        fake_context = AsyncMock()
        fake_context.new_page = AsyncMock(return_value=fake_page)
        fake_context.close = AsyncMock()

        fake_browser = AsyncMock()
        fake_browser.new_context = AsyncMock(return_value=fake_context)
        fake_browser.close = AsyncMock()

        fake_pw = AsyncMock()
        fake_pw.chromium = MagicMock()
        fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)
        fake_pw.stop = AsyncMock()

        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=fake_pw)
            artifact, data = await recorder.screenshot("http://localhost:8000", "homepage")

        assert artifact.type == ArtifactType.SCREENSHOT
        assert artifact.label == "homepage"
        assert artifact.mime_type == "image/png"
        assert data == b"\x89PNG_FAKE_DATA"
        assert artifact.size_bytes == len(data)

    async def test_screenshot_multi_returns_multiple_artifacts(self, recorder):
        """screenshot_multi captures at each breakpoint width."""
        call_count = 0

        fake_page = AsyncMock()
        fake_page.wait_for_timeout = AsyncMock()
        fake_page.goto = AsyncMock()

        async def make_screenshot(**kwargs):
            nonlocal call_count
            call_count += 1
            return b"\x89PNG" + bytes([call_count])

        fake_page.screenshot = make_screenshot

        fake_context = AsyncMock()
        fake_context.new_page = AsyncMock(return_value=fake_page)
        fake_context.close = AsyncMock()

        fake_browser = AsyncMock()
        fake_browser.new_context = AsyncMock(return_value=fake_context)
        fake_browser.close = AsyncMock()

        fake_pw = AsyncMock()
        fake_pw.chromium = MagicMock()
        fake_pw.chromium.launch = AsyncMock(return_value=fake_browser)
        fake_pw.stop = AsyncMock()

        with patch(
            "playwright.async_api.async_playwright"
        ) as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=fake_pw)
            results = await recorder.screenshot_multi(
                "http://localhost:8000", "test", breakpoints=(1280, 768)
            )

        assert len(results) == 2
        assert results[0][0].label == "test_1280w"
        assert results[1][0].label == "test_768w"


class TestClose:
    async def test_close_without_browser_is_safe(self, recorder):
        """Closing without starting should not raise."""
        await recorder.close()


class TestInit:
    def test_default_viewport(self):
        r = PlaywrightRecorder()
        assert r._viewport == {"width": 1280, "height": 720}

    def test_custom_viewport(self):
        r = PlaywrightRecorder(viewport_width=1920, viewport_height=1080)
        assert r._viewport == {"width": 1920, "height": 1080}
