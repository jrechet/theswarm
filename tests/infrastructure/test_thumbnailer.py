"""F4 — thumbnailer.make_thumbnail + make_gif."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from theswarm.infrastructure.recording import thumbnailer
from theswarm.infrastructure.recording.thumbnailer import (
    ThumbnailError,
    make_gif,
    make_thumbnail,
)


@pytest.fixture(scope="module")
def tiny_webm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a ~2s, 160x120 webm via the bundled ffmpeg."""
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out = tmp_path_factory.mktemp("thumbs") / "tiny.webm"

    # 2s solid color + moving box, libvpx (webm). Keeps size tiny (<100 KB).
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=2:size=160x120:rate=10",
            "-c:v", "libvpx",
            "-b:v", "50k",
            "-an",
            str(out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert out.exists() and out.stat().st_size > 0
    return out


async def test_make_thumbnail_produces_nonzero_jpeg(tiny_webm: Path, tmp_path: Path):
    out = tmp_path / "thumb.jpg"
    result = await make_thumbnail(tiny_webm, out, at_seconds=0.5)

    assert result == out
    assert result.exists()
    assert result.stat().st_size > 0
    # JPEG magic bytes
    header = result.read_bytes()[:3]
    assert header == b"\xff\xd8\xff"


async def test_make_gif_produces_nonzero_gif(tiny_webm: Path, tmp_path: Path):
    out = tmp_path / "preview.gif"
    result = await make_gif(tiny_webm, out, max_seconds=1.0, fps=5, width=120)

    assert result == out
    assert result.exists()
    assert result.stat().st_size > 0
    # GIF magic bytes
    header = result.read_bytes()[:6]
    assert header in (b"GIF87a", b"GIF89a")


async def test_make_thumbnail_raises_when_video_missing(tmp_path: Path):
    bogus = tmp_path / "nope.webm"
    with pytest.raises(ThumbnailError) as exc:
        await make_thumbnail(bogus, tmp_path / "thumb.jpg")
    assert "not found" in str(exc.value).lower()


async def test_make_gif_raises_when_video_missing(tmp_path: Path):
    bogus = tmp_path / "nope.webm"
    with pytest.raises(ThumbnailError) as exc:
        await make_gif(bogus, tmp_path / "preview.gif")
    assert "not found" in str(exc.value).lower()


async def test_missing_ffmpeg_raises_thumbnail_error(tmp_path: Path, monkeypatch):
    """When no ffmpeg is available, we raise a clean ThumbnailError."""
    # Force imageio_ffmpeg.get_ffmpeg_exe() to fail
    import imageio_ffmpeg

    def _boom():
        raise RuntimeError("no binary")

    monkeypatch.setattr(imageio_ffmpeg, "get_ffmpeg_exe", _boom)
    # And make shutil.which return None
    monkeypatch.setattr(thumbnailer.shutil, "which", lambda _name: None)

    # Create a tiny dummy file so we pass the existence check
    video = tmp_path / "tiny.webm"
    video.write_bytes(b"dummy")

    with pytest.raises(ThumbnailError) as exc:
        await make_thumbnail(video, tmp_path / "thumb.jpg")
    msg = str(exc.value).lower()
    assert "ffmpeg" in msg
    assert "not available" in msg


async def test_make_thumbnail_raises_on_nonvideo_input(tmp_path: Path):
    """An input that ffmpeg can't decode produces ThumbnailError, not a crash."""
    bogus = tmp_path / "junk.webm"
    bogus.write_bytes(b"not actually a video")
    with pytest.raises(ThumbnailError):
        await make_thumbnail(bogus, tmp_path / "thumb.jpg")


async def test_make_thumbnail_creates_parent_dir(tiny_webm: Path, tmp_path: Path):
    nested = tmp_path / "a" / "b" / "c" / "thumb.jpg"
    await make_thumbnail(tiny_webm, nested, at_seconds=0.25)
    assert nested.exists()
    assert nested.stat().st_size > 0


async def test_concurrent_thumbnail_and_gif(tiny_webm: Path, tmp_path: Path):
    """Thumbnail + GIF can run concurrently without ffmpeg arg collisions."""
    thumb, gif = await asyncio.gather(
        make_thumbnail(tiny_webm, tmp_path / "thumb.jpg", at_seconds=0.5),
        make_gif(tiny_webm, tmp_path / "preview.gif", max_seconds=1.0, fps=5, width=120),
    )
    assert thumb.exists() and thumb.stat().st_size > 0
    assert gif.exists() and gif.stat().st_size > 0


# ── default seek: midpoint of the video, never frame 0 ──────────────────
#
# Prod cycle 5f8f0f63f58c's demo thumbnail was frame 0 — a blank white page
# — because the previous default seeked to a fixed 1s in, which lands on
# the walkthrough's loading screen whenever the target is still booting.


def test_seek_args_midpoint_of_known_duration():
    assert thumbnailer._seek_args(10.0) == ["-ss", "5.00"]


def test_seek_args_last_frame_when_duration_unknown():
    assert thumbnailer._seek_args(None) == ["-sseof", "-1"]


def test_seek_args_last_frame_when_duration_is_zero():
    assert thumbnailer._seek_args(0.0) == ["-sseof", "-1"]


async def test_default_thumbnail_seeks_to_the_midpoint(tiny_webm: Path, tmp_path: Path, monkeypatch):
    """No `at_seconds` given: ffmpeg is called with `-ss` at half the real
    duration (the tiny_webm fixture is ~2s), never at 0."""
    captured = {}

    async def fake_run_ffmpeg(args):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"\xff\xd8\xff\x00")  # satisfy the post-check

    monkeypatch.setattr(thumbnailer, "_run_ffmpeg", fake_run_ffmpeg)

    await make_thumbnail(tiny_webm, tmp_path / "thumb.jpg")

    args = captured["args"]
    assert "-ss" in args
    seek_value = float(args[args.index("-ss") + 1])
    assert 0.5 < seek_value < 1.5  # midpoint of ~2s, nowhere near frame 0


async def test_thumbnail_falls_back_to_last_frame_when_duration_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnailer, "_probe_duration", AsyncMock(return_value=None))
    captured = {}

    async def fake_run_ffmpeg(args):
        captured["args"] = args
        Path(args[-1]).write_bytes(b"\xff\xd8\xff\x00")

    monkeypatch.setattr(thumbnailer, "_run_ffmpeg", fake_run_ffmpeg)

    video = tmp_path / "video.webm"
    video.write_bytes(b"dummy")

    await make_thumbnail(video, tmp_path / "thumb.jpg")

    args = captured["args"]
    assert "-sseof" in args
    assert args[args.index("-sseof") + 1] == "-1"


async def test_probe_duration_parses_ffmpeg_banner(monkeypatch):
    banner = b"Duration: 00:01:02.50, start: 0.000000, bitrate: 128 kb/s"

    class FakeProc:
        async def communicate(self):
            return b"", banner

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    duration = await thumbnailer._probe_duration("ffmpeg", Path("whatever.webm"))
    assert duration == 62.5


async def test_probe_duration_returns_none_without_a_banner(monkeypatch):
    class FakeProc:
        async def communicate(self):
            return b"", b"no duration line here"

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    duration = await thumbnailer._probe_duration("ffmpeg", Path("whatever.webm"))
    assert duration is None
