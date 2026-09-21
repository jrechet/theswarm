"""The Dev's gate runs the tests its own diff touches, not the whole suite.

Giving the Dev QA's 900s budget made the gate able to measure a real suite —
and made one iteration cost up to an hour, because the Ralph retry runs that
suite a second time (`dev_iter` had to go from 30 to 60 minutes to hold it).
Five iterations then span five hours on a target this size.

Owner's decision (2026-09-20), after seeing that arithmetic: run only what
the diff touches. The Dev gets a fast, relevant signal before opening its PR;
the whole suite stays QA's job and the repository's CI's.

A diff that maps to no test file is reported as not run — the honest answer
already used elsewhere — rather than silently passing or dragging the whole
suite back in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from theswarm.agents.dev import _impacted_tests, run_quality_gates


def _touch(root, rel: str, body: str = "def test_x(): pass\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_a_changed_test_file_is_run_directly(tmp_path):
    _touch(tmp_path, "tests/test_widget.py")

    assert _impacted_tests(str(tmp_path), ["tests/test_widget.py"]) == [
        "tests/test_widget.py",
    ]


def test_a_changed_source_file_pulls_in_its_test(tmp_path):
    _touch(tmp_path, "src/theswarm/application/services/guard.py", "x = 1\n")
    _touch(tmp_path, "tests/application/test_guard.py")

    impacted = _impacted_tests(
        str(tmp_path), ["src/theswarm/application/services/guard.py"],
    )

    assert impacted == ["tests/application/test_guard.py"]


def test_both_halves_of_one_change_are_deduplicated(tmp_path):
    _touch(tmp_path, "src/theswarm/agents/dev.py", "x = 1\n")
    _touch(tmp_path, "tests/test_dev.py")

    impacted = _impacted_tests(
        str(tmp_path), ["src/theswarm/agents/dev.py", "tests/test_dev.py"],
    )

    assert impacted == ["tests/test_dev.py"]


def test_a_source_file_with_no_test_maps_to_nothing(tmp_path):
    _touch(tmp_path, "src/theswarm/lonely.py", "x = 1\n")

    assert _impacted_tests(str(tmp_path), ["src/theswarm/lonely.py"]) == []


def test_a_deleted_file_is_not_offered_to_pytest(tmp_path):
    """`git diff --name-only` lists removals too; pytest would just error."""
    assert _impacted_tests(str(tmp_path), ["tests/test_gone.py"]) == []


def test_non_python_changes_are_ignored(tmp_path):
    _touch(tmp_path, "README.md", "# hi\n")

    assert _impacted_tests(str(tmp_path), ["README.md"]) == []


def test_the_order_is_stable(tmp_path):
    """A stable command line keeps logs and reruns comparable."""
    for rel in ("tests/test_b.py", "tests/test_a.py", "tests/test_c.py"):
        _touch(tmp_path, rel)

    impacted = _impacted_tests(
        str(tmp_path), ["tests/test_c.py", "tests/test_a.py", "tests/test_b.py"],
    )

    assert impacted == sorted(impacted)


# ── the gate itself ───────────────────────────────────────────────────


class _FakeClaude:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        return {"passed": True, "output": "1 passed", "exit_code": 0}


def _pytest_targets(claude: _FakeClaude) -> list[str]:
    for command in claude.commands:
        if "pytest" in command:
            return [a for a in command if a.endswith(".py") or a == "tests/"]
    return []


async def _gate(tmp_path, changed: list[str]):
    claude = _FakeClaude()
    with patch("theswarm.tools.git.changed_files",
               new=AsyncMock(return_value=changed)):
        await run_quality_gates({
            "task": {"number": 1}, "workspace": str(tmp_path), "claude": claude,
        })
    return claude


async def test_the_gate_runs_only_the_touched_files(tmp_path):
    _touch(tmp_path, "src/theswarm/thing.py", "x = 1\n")
    _touch(tmp_path, "tests/test_thing.py")
    _touch(tmp_path, "tests/test_unrelated.py")

    claude = await _gate(tmp_path, ["src/theswarm/thing.py"])

    assert _pytest_targets(claude) == ["tests/test_thing.py"]


async def test_an_unknown_diff_falls_back_to_the_whole_suite(tmp_path):
    """A resumed branch or a missing base ref must not skip the gate."""
    _touch(tmp_path, "tests/test_thing.py")

    claude = await _gate(tmp_path, [])

    assert _pytest_targets(claude) == ["tests/"]


async def test_a_diff_touching_no_test_is_reported_not_run(tmp_path):
    _touch(tmp_path, "README.md", "# hi\n")
    claude = _FakeClaude()

    with patch("theswarm.tools.git.changed_files",
               new=AsyncMock(return_value=["README.md"])):
        result = await run_quality_gates({
            "task": {"number": 1}, "workspace": str(tmp_path), "claude": claude,
        })

    assert result["tests_unavailable"]
    assert not _pytest_targets(claude)
