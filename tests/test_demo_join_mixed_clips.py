"""Joining demo films keeps every part, whatever each was encoded with.

2026-09-29: the review-conversation demo was a joined film (VP9) plus a
raw Playwright clip (VP8). ffmpeg's concat *demuxer* needs one codec for
every input: it wrote the first and dropped the rest without an error —
the demo lost the Dev's answer, the second review and the board, and
looked finished. The concat *filter* decodes each input.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="ffmpeg is not installed here")


def _recorder():
    pytest.importorskip("playwright.sync_api")
    spec = importlib.util.spec_from_file_location("record_v2_demo_join", ROOT / "scripts/record_v2_demo.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _clip(path: pathlib.Path, codec: str, seconds: int, size: str) -> pathlib.Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size={size}:rate=25", "-c:v", codec, str(path)],
                   check=True)
    return path


def _duration(path: pathlib.Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                          "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def test_a_joined_film_and_a_raw_clip_keep_both_parts(tmp_path, monkeypatch):
    film = _recorder()
    monkeypatch.setattr(film, "WORK", tmp_path)
    (tmp_path / "videos").mkdir()
    first = _clip(tmp_path / "joined.webm", "libvpx-vp9", 3, "1280x720")
    second = _clip(tmp_path / "raw.webm", "libvpx", 2, "640x360")
    out = tmp_path / "out.webm"

    film.join([first, second], out)

    assert _duration(out) == pytest.approx(5.0, abs=0.5)
