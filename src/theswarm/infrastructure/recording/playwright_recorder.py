"""Playwright-based Recorder implementation for capturing screenshots and videos."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from theswarm.domain.reporting.value_objects import Artifact, ArtifactType

log = logging.getLogger(__name__)


# A JSON answer drawn so it can be read in a thumbnail or a video: the
# request and its status on top, the body pretty-printed below, large. The
# pages a cycle's PRs add are often API routes, and Chromium drew them as
# one 13px line on a white page (docs/demos/qa-feature-pages.webm).
_PRESENT_JSON = """
([path, status]) => {
  if (!/json/i.test(document.contentType || "")) return false;
  const source = document.querySelector("pre") || document.body;
  let pretty;
  try { pretty = JSON.stringify(JSON.parse(source.textContent), null, 2); }
  catch (e) { return false; }
  document.head.innerHTML = '<meta charset="utf-8"><style>'
    + 'html,body{margin:0;background:#FAF8F3;color:#1F1C17}'
    + 'body{padding:40px 56px;font:20px/1.55 ui-monospace,"IBM Plex Mono",Menlo,monospace}'
    + 'header{font:600 16px/1.4 system-ui,sans-serif;color:#7A6F5E;letter-spacing:.02em;'
    + 'margin-bottom:22px;padding-bottom:14px;border-bottom:1px solid #E4DDCF}'
    + 'pre{margin:0;white-space:pre-wrap;word-break:break-word}</style>';
  const header = document.createElement("header");
  header.textContent = "GET " + path + (status ? " \u2192 " + status : "");
  const pre = document.createElement("pre");
  pre.textContent = pretty;
  document.body.replaceChildren(header, pre);
  return true;
}
"""


_TEXT_STYLE = (
    '<meta charset="utf-8"><style>'
    "html,body{margin:0;background:#FAF8F3;color:#1F1C17}"
    'body{padding:40px 56px;font:18px/1.55 ui-monospace,"IBM Plex Mono",Menlo,monospace}'
    "header{font:600 16px/1.4 system-ui,sans-serif;color:#7A6F5E;letter-spacing:.02em;"
    "margin-bottom:22px;padding-bottom:14px;border-bottom:1px solid #E4DDCF}"
    "pre{margin:0;white-space:pre-wrap;word-break:break-word}</style>"
)


async def present_text(page, path: str, status: int | None, content_type: str, body: str) -> None:
    """Draw an answer a browser would download (`text/calendar`, `text/csv`, …)
    as the request and its body. Chromium started a download on the
    ical-feed cycle's `calendar.ics`: no screenshot, no frame of the video."""
    import html

    kind = (content_type or "").split(";")[0].strip()
    head = f"GET {path}" + (f" \u2192 {status}" if status else "") + (f" \u00b7 {kind}" if kind else "")
    await page.set_content(
        f"<html><head>{_TEXT_STYLE}</head><body><header>{html.escape(head)}</header>"
        f"<pre>{html.escape(body[:20_000])}</pre></body></html>"
    )


_EXCHANGE_STYLE = _TEXT_STYLE.replace(
    "</style>",
    "p.caption{font:600 24px/1.35 system-ui,sans-serif;margin:0 0 20px;color:#1F1C17}"
    "h2{font:600 12px/1 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;"
    "color:#7A6F5E;margin:26px 0 10px}"
    "pre.request{color:#5B4A2E}</style>",
)


def _pretty(body: object) -> str:
    """A JSON body indented for the screen; anything else as it came."""
    if body is None or body == "":
        return ""
    if not isinstance(body, str):
        return json.dumps(body, indent=2, ensure_ascii=False)
    try:
        return json.dumps(json.loads(body), indent=2, ensure_ascii=False)
    except ValueError:
        return body


async def present_exchange(page, exchange: dict) -> None:
    """Draw one call of a feature's demo (`qa_feature_calls`): the request and
    its status on top, the caption a viewer reads, the body sent and the
    answer, pretty-printed. sell-tickets had nothing to show but GET pages."""
    import html

    status = exchange.get("status")
    head = f"{exchange.get('method', 'GET')} {exchange.get('path', '/')}" + (
        f" → {status}" if status else " → no answer")
    parts = [f"<header>{html.escape(head)}</header>"]
    if exchange.get("caption"):
        parts.append(f'<p class="caption">{html.escape(exchange["caption"])}</p>')
    sent = _pretty(exchange.get("request"))
    if sent:
        parts.append(f'<h2>Sent</h2><pre class="request">{html.escape(sent)}</pre>')
    parts.append(f"<h2>Answer</h2><pre>{html.escape(_pretty(exchange.get('body', ''))[:20_000])}</pre>")
    await page.set_content(f"<html><head>{_EXCHANGE_STYLE}</head><body>{''.join(parts)}</body></html>")


async def present_json(page, path: str, status: int | None) -> bool:
    """Redraw the page if it is a JSON answer; False when it is not."""
    try:
        return bool(await page.evaluate(_PRESENT_JSON, [path, status]))
    except Exception:  # noqa: BLE001 — a demo page as it came is still a demo page
        log.debug("present_json: could not redraw %s", path, exc_info=True)
        return False


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
            response = await page.goto(url, wait_until="networkidle", timeout=15000)
            await present_json(page, urlparse(url).path or "/", getattr(response, "status", None))
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

    async def screenshot_text(
        self, url: str, label: str, *, status: int | None, content_type: str, body: str,
    ) -> tuple[Artifact, bytes]:
        """A screenshot of an answer drawn as text (`present_text`)."""
        browser = await self._ensure_browser()
        context = await browser.new_context(viewport=self._viewport)
        page = await context.new_page()
        try:
            await present_text(page, urlparse(url).path or "/", status, content_type, body)
            data = await page.screenshot(full_page=True, type="png")
        finally:
            await context.close()
        artifact = Artifact(
            type=ArtifactType.SCREENSHOT, label=label, path="", mime_type="image/png",
            size_bytes=len(data), created_at=datetime.now(timezone.utc),
        )
        log.info("PlaywrightRecorder: text screenshot '%s' (%d bytes) from %s", label, len(data), url)
        return artifact, data

    async def screenshot_exchange(self, exchange: dict) -> tuple[Artifact, bytes]:
        """A screenshot of one demo call drawn by `present_exchange`."""
        browser = await self._ensure_browser()
        context = await browser.new_context(viewport=self._viewport)
        page = await context.new_page()
        try:
            await present_exchange(page, exchange)
            data = await page.screenshot(full_page=True, type="png")
        finally:
            await context.close()
        label = exchange.get("label") or "feature_call"
        artifact = Artifact(
            type=ArtifactType.SCREENSHOT, label=label, path="", mime_type="image/png",
            size_bytes=len(data), created_at=datetime.now(timezone.utc),
        )
        log.info("PlaywrightRecorder: exchange screenshot '%s' (%d bytes)", label, len(data))
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
