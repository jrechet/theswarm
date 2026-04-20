"""Playwright-based Recorder implementation for capturing screenshots and videos."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from theswarm.domain.reporting.value_objects import Artifact, ArtifactType

log = logging.getLogger(__name__)


class PlaywrightRecorder:
    """Captures screenshots and screen recordings using Playwright.

    Implements the Recorder protocol from domain/reporting/ports.py.
    Uses async Playwright to launch a headless Chromium browser.
    """

    def __init__(self, viewport_width: int = 1280, viewport_height: int = 720) -> None:
        self._viewport = {"width": viewport_width, "height": viewport_height}
        self._playwright: object | None = None
        self._browser: object | None = None
        self._recording_context: object | None = None
        self._recording_page: object | None = None
        self._recording_label: str = ""

    async def _ensure_browser(self) -> object:
        """Lazily start Playwright and launch browser."""
        if self._browser is not None:
            return self._browser

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        log.info("PlaywrightRecorder: browser launched")
        return self._browser

    async def close(self) -> None:
        """Shut down browser and Playwright."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def screenshot(self, url: str, label: str) -> tuple[Artifact, bytes]:
        """Navigate to url and capture a full-page screenshot."""
        browser = await self._ensure_browser()
        context = await browser.new_context(viewport=self._viewport)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=15000)
            # Small wait for any JS animations to settle
            await page.wait_for_timeout(500)
            data = await page.screenshot(full_page=True, type="png")
        finally:
            await context.close()

        artifact = Artifact(
            type=ArtifactType.SCREENSHOT,
            label=label,
            path="",  # filled by ArtifactStore.save()
            mime_type="image/png",
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
        )

        log.info("PlaywrightRecorder: screenshot '%s' (%d bytes) from %s", label, len(data), url)
        return artifact, data

    async def screenshot_multi(
        self, url: str, label: str, breakpoints: tuple[int, ...] = (1280, 768, 375),
    ) -> list[tuple[Artifact, bytes]]:
        """Capture screenshots at multiple viewport widths (responsive check)."""
        browser = await self._ensure_browser()
        results: list[tuple[Artifact, bytes]] = []

        for width in breakpoints:
            viewport = {"width": width, "height": self._viewport["height"]}
            context = await browser.new_context(viewport=viewport)
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.wait_for_timeout(500)
                data = await page.screenshot(full_page=True, type="png")
            finally:
                await context.close()

            bp_label = f"{label}_{width}w"
            artifact = Artifact(
                type=ArtifactType.SCREENSHOT,
                label=bp_label,
                path="",
                mime_type="image/png",
                size_bytes=len(data),
                created_at=datetime.now(timezone.utc),
            )
            results.append((artifact, data))
            log.info("PlaywrightRecorder: screenshot '%s' (%d bytes)", bp_label, len(data))

        return results

    async def capture_before_after(
        self,
        before_url: str | None,
        after_url: str,
        label: str,
    ) -> list[tuple[Artifact, bytes]]:
        """Capture a before/after screenshot pair for a single story.

        F2 — when ``before_url`` is ``None`` (no baseline deployed main yet),
        only the ``after`` artifact is returned and a warning is logged so
        the story id surfaces in ops.
        """
        results: list[tuple[Artifact, bytes]] = []

        if before_url:
            before = await self.screenshot(before_url, f"{label}_before")
            results.append(before)
        else:
            log.warning(
                "PlaywrightRecorder: no before_url for story '%s' — skipping before capture",
                label,
            )

        after = await self.screenshot(after_url, f"{label}_after")
        results.append(after)
        return results

    async def start_recording(self, url: str) -> None:
        """Start a video recording of the given URL."""
        import tempfile

        browser = await self._ensure_browser()
        tmp_dir = tempfile.mkdtemp(prefix="swarm-recording-")

        self._recording_context = await browser.new_context(
            viewport=self._viewport,
            record_video_dir=tmp_dir,
            record_video_size=self._viewport,
        )
        self._recording_page = await self._recording_context.new_page()
        await self._recording_page.goto(url, wait_until="networkidle", timeout=15000)
        self._recording_label = f"recording_{uuid.uuid4().hex[:8]}"
        log.info("PlaywrightRecorder: recording started for %s", url)

    async def stop_recording(self) -> tuple[Artifact, bytes]:
        """Stop recording and return the video artifact."""
        if self._recording_context is None or self._recording_page is None:
            raise RuntimeError("No recording in progress")

        video = self._recording_page.video
        await self._recording_context.close()

        video_path = await video.path()
        with open(video_path, "rb") as f:
            data = f.read()

        artifact = Artifact(
            type=ArtifactType.VIDEO,
            label=self._recording_label,
            path="",
            mime_type="video/webm",
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
        )

        self._recording_context = None
        self._recording_page = None
        log.info("PlaywrightRecorder: recording stopped (%d bytes)", len(data))
        return artifact, data
