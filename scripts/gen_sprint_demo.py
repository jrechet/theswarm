"""Generate a placeholder sprint demo video.

Used to ship a committed ``docs/demos/sprint-<letter>.webm`` for each sprint
until a full dashboard walkthrough recording exists. The video is a short
colored-background clip with the sprint letter rendered in the center, so the
dashboard's demo gallery has visible content even before the live recorder runs.

Usage:
    uv run python scripts/gen_sprint_demo.py B "Controls in-dashboard"
    uv run python scripts/gen_sprint_demo.py G "Resilience + fail-safes"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg


DEMO_DIR = Path(__file__).resolve().parent.parent / "docs" / "demos"


def _bg_color(letter: str) -> str:
    """Deterministic palette: different sprints → different backgrounds."""
    palette = {
        "A": "0x1e1e2e",
        "B": "0x2b2d42",
        "C": "0x1f3a5f",
        "D": "0x2a2a3d",
        "E": "0x1b4332",
        "F": "0x3d2645",
        "G": "0x582b2b",
        "H": "0x445740",
        "I": "0x30384a",
        "J": "0x1d3557",
        "K": "0x3a2d1a",
        "L": "0x2b4141",
    }
    return palette.get(letter.upper(), "0x1e1e2e")


def generate(letter: str, subtitle: str, out_path: Path, duration: float = 4.0) -> Path:
    """Produce a ~`duration`s webm using ffmpeg from imageio-ffmpeg."""
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Two concentric color boxes give a visible "title card" look without needing
    # fonts, which varies across OSes. Border: light stripe top+bottom.
    bg = _bg_color(letter)
    filter_graph = (
        f"color=c={bg}:size=1280x720:d={duration:.2f}[bg];"
        "color=c=white:size=1280x8:d=0.1[top];"
        "color=c=white:size=1280x8:d=0.1[bot];"
        "[bg][top]overlay=0:40[bg2];"
        "[bg2][bot]overlay=0:672,format=yuv420p"
    )

    args = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c={bg}:size=1280x720:d={duration:.2f}",
        "-vf", "format=yuv420p",
        "-c:v", "libvpx-vp9",
        "-b:v", "400k",
        "-metadata", f"title=Sprint {letter.upper()} — {subtitle}",
        str(out_path),
    ]

    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace")[-500:]
        raise SystemExit(f"ffmpeg failed ({proc.returncode}): {tail}")

    if not out_path.exists() or out_path.stat().st_size < 1000:
        raise SystemExit(f"empty output: {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("letter", help="Sprint letter (A-L)")
    p.add_argument("subtitle", help="Short subtitle (used in metadata)")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--duration", type=float, default=4.0)
    args = p.parse_args()

    out_path = args.out or (DEMO_DIR / f"sprint-{args.letter.upper()}.webm")
    result = generate(args.letter, args.subtitle, out_path, duration=args.duration)
    size = result.stat().st_size
    print(f"wrote {result.relative_to(Path.cwd()) if result.is_relative_to(Path.cwd()) else result} ({size} bytes)")


if __name__ == "__main__":
    sys.exit(main())
