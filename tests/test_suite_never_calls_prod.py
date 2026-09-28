"""No test reaches prod: the harness a test loads points at a closed port.

tests/test_harness_dead_story.py called the live API through `past_runs`
for months without anyone noticing — prod answered fast. On 2026-09-28
prod was down, each call waited out its 60 s timeout, and the suite went
from 3½ to 10½ minutes.
"""

from __future__ import annotations

import importlib.util
import pathlib
import time


def test_the_harness_in_the_suite_points_at_a_closed_local_port():
    spec = importlib.util.spec_from_file_location(
        "cycle_e2e_guard", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py",
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    assert harness.BASE.startswith("http://127.0.0.1:9")
    started = time.monotonic()
    status, _ = harness._api("/health")
    assert status == 0 and time.monotonic() - started < 5
