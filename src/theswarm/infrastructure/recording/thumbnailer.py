"""F4 — thumbnail + GIF generation from video artifacts via ffmpeg.

Shells out to the ffmpeg binary bundled with ``imageio-ffmpeg`` so we don't
depend on a system install. Both :func:`make_thumbnail` and :func:`make_gif`
return the output :class:`Path` on success and raise :class:`ThumbnailError`
with a short message on failure — no stack trace leaks into the caller's logs.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


class ThumbnailError(RuntimeError):
    """Raised when thumbnail / gif generation fails.

    Carries a short, user-safe message. The underlying ffmpeg stderr is logged
    but not re-raised.
    """


def _resolve_ffmpeg() -> str:
    """Locate an ffmpeg binary. Prefer ``imageio-ffmpeg``, fall back to PATH.

    Raises :class:`ThumbnailError` when no binary is available.
    """
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001 — any provider error = fallback
        log.warning("imageio_ffmpeg.get_ffmpeg_exe failed: %s", e)

    exe = shutil.which("ffmpeg")
    if exe:
        return exe

    raise ThumbnailError(
        "ffmpeg binary not available (install imageio-ffmpeg or ffmpeg)",
    )


async def _run_ffmpeg(args: list[str]) -> None:
    """Invoke ffmpeg and raise :class:`ThumbnailError` on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace")[-400:].strip()
        log.warning("ffmpeg failed (rc=%s): %s", proc.returncode, tail)
        raise ThumbnailError(f"ffmpeg exited with code {proc.returncode}")


async def make_thumbnail(
    video_path: Path,
    out_path: Path,
    at_seconds: float = 1.0,
) -> Path:
    """Extract a single JPEG frame from ``video_path`` at ``at_seconds``.

    Creates the parent directory if needed. Returns the output path.
    """
    video_path = Path(video_path)
    out_path = Path(out_path)

    if not video_path.exists():
        raise ThumbnailError(f"video not found: {video_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _resolve_ffmpeg()
    # -y: overwrite · -ss: seek · -frames:v 1: single frame · -q:v 3: JPEG quality
    args = [
        ffmpeg,
        "-y",
        "-ss", f"{max(0.0, at_seconds):.2f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "3",
        str(out_path),
    ]
    await _run_ffmpeg(args)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ThumbnailError("ffmpeg produced an empty thumbnail")

    log.info("thumbnailer: wrote %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


async def make_gif(
    video_path: Path,
    out_path: Path,
    max_seconds: float = 8.0,
    fps: int = 10,
    width: int = 640,
) -> Path:
    """Render a short animated GIF from ``video_path``.

    Uses a palettegen+paletteuse filter graph to keep the result small and
    visually clean. Returns the output path.
    """
    video_path = Path(video_path)
    out_path = Path(out_path)

    if not video_path.exists():
        raise ThumbnailError(f"video not found: {video_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _resolve_ffmpeg()
    vf = (
        f"fps={max(1, fps)},"
        f"scale={max(16, width)}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    )
    args = [
        ffmpeg,
        "-y",
        "-t", f"{max(0.1, max_seconds):.2f}",
        "-i", str(video_path),
        "-vf", vf,
        "-loop", "0",
        str(out_path),
    ]
    await _run_ffmpeg(args)

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise ThumbnailError("ffmpeg produced an empty gif")

    log.info("thumbnailer: wrote %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path
