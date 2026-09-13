"""Every cycle a person can start must write checkpoints.

Prod, 2026-09-13: a deploy interrupted cycle 84a886fcc5e1 and startup logged
"1 interrupted cycle(s), resuming 0". The resume machinery (#75) was sound;
it had nothing to read. `cycle_checkpoints` held 23 rows — all from
scheduled cycles, which pass checkpoint_repo — while Play and POST /api/cycle
did not pass it at all. The cycles people actually start were exactly the
ones that could never be resumed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTES = Path("src/theswarm/presentation/web/routes")


def _run_api_cycle_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text())
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_api_cycle"
    ]


def _entry_points() -> list[tuple[Path, ast.Call]]:
    found: list[tuple[Path, ast.Call]] = []
    for path in sorted(ROUTES.glob("*.py")):
        found.extend((path, call) for call in _run_api_cycle_calls(path))
    return found


def test_there_are_entry_points_to_check():
    """Guard the guard: a rename must not turn this file into a no-op."""
    assert len(_entry_points()) >= 3


@pytest.mark.parametrize(
    "path, call",
    _entry_points(),
    ids=[f"{p.name}:{c.lineno}" for p, c in _entry_points()],
)
def test_every_cycle_entry_point_passes_checkpoint_repo(path, call):
    passed = {kw.arg for kw in call.keywords}
    assert "checkpoint_repo" in passed, (
        f"{path.name}:{call.lineno} starts a cycle without checkpoint_repo — "
        "it can never be resumed after a restart"
    )


def test_run_api_cycle_still_accepts_the_argument():
    """If the signature drops it, the calls above become silent no-ops."""
    from theswarm.api import run_api_cycle
    import inspect

    assert "checkpoint_repo" in inspect.signature(run_api_cycle).parameters
