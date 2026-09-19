"""A failed dependency install is `tests_unavailable`, not a red suite.

Local cycle `targeted-160-20260919T133731Z` on this repository:
`find_system_python` picked a 3.11 interpreter for a project declaring
`requires-python = ">=3.12"`, so `pip install -e .` failed with
`Package 'theswarm' requires a different Python`. `install_target` logged
that and threw it away, returning only a fingerprint.

pytest then ran — it *was* installed — and every test file errored on
import because the target package was not. `_test_runner_missing` looks for
"pytest is missing" markers, found none, and the Dev read 165 import errors
as a red suite: two Ralph rounds, twenty minutes of Claude calls that wrote
zero files, and a PR whose body claimed "Some tests failing — needs review"
when the tests had never run. QA, on the same workspace, reported
`unit=165(fail)`.

AGENTS.md already states the intended contract for this case: no Ralph
rounds, the reason in the PR body, and the repository's CI as the judge.
"""

from __future__ import annotations

from theswarm.agents.dev import run_quality_gates
from theswarm.agents.qa import run_unit_tests

_INSTALL_ERROR = (
    "ERROR: Package 'theswarm' requires a different Python: "
    "3.11.6 not in '>=3.12'"
)


class _InstallFailsClaude:
    """pip fails; pytest itself runs fine and reports import errors."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        if "pip" in command:
            return {"passed": False, "output": _INSTALL_ERROR, "exit_code": 1}
        return {
            "passed": False,
            "exit_code": 2,
            "output": (
                "ERROR tests/test_cycle.py\nERROR tests/test_dev.py\n"
                "!!!! Interrupted: 165 errors during collection !!!!"
            ),
        }


def _workspace(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    return str(tmp_path)


async def test_dev_reports_the_install_failure_instead_of_red_tests(tmp_path):
    claude = _InstallFailsClaude()

    result = await run_quality_gates(
        {"task": {"number": 1}, "workspace": _workspace(tmp_path),
         "claude": claude},
    )

    assert result["tests_unavailable"], (
        "a failed install leaves the suite unrunnable; reporting it as red "
        "tests costs two Ralph rounds and files a PR with a false claim"
    )
    assert "requires a different Python" in result["tests_unavailable"]


async def test_qa_marks_the_unit_run_not_run_when_the_install_failed(tmp_path):
    claude = _InstallFailsClaude()

    result = await run_unit_tests(
        {"workspace": _workspace(tmp_path), "claude": claude},
    )

    assert result.get("unit_tests_not_run_reason"), (
        "QA read the same import errors as unit=165(fail); the install "
        "never succeeded, so nothing was measured"
    )
