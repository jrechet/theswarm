"""The quality gate installs what the target actually declares, and knows
the difference between red tests and no test runner.

TheSwarm is a pyproject/uv project with no requirements.txt. The gate
installed nothing, `python -m pytest` answered "No module named pytest",
that read as "tests failed", and the Ralph Loop asked Claude twice to fix
tests that had never run — the second attempt broke the syntax of the file
under edit (cycle f12107432167, #88). Not one PR came out of the swarm's
own repository, and the reason was never on screen.
"""

from __future__ import annotations

from theswarm.agents.dev import (
    TEST_RUN_TIMEOUT_SECONDS,
    _dev_dependencies,
    _install_plan,
    _should_retry,
    _test_runner_missing,
    run_quality_gates,
)

PY = "/usr/local/bin/python3"


class _FakeClaude:
    def __init__(self, test_output="1 passed", exit_code=0) -> None:
        self.commands: list[list[str]] = []
        self.test_output = test_output
        self.exit_code = exit_code

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        if "pip" in command:
            return {"passed": True, "output": "", "exit_code": 0}
        return {
            "passed": self.exit_code == 0,
            "output": self.test_output,
            "exit_code": self.exit_code,
        }


def _pip_calls(claude: _FakeClaude) -> list[list[str]]:
    return [c for c in claude.commands if "pip" in c]


THESWARM_PYPROJECT = """
[project]
name = "theswarm"
version = "1.0.0"
dependencies = ["langgraph>=0.2", "fastapi>=0.110"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    {include-group = "lint"},
]
lint = ["ruff>=0.5"]
"""


class TestInstallPlan:
    def test_requirements_txt_keeps_the_old_path(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)

        commands, fingerprint = _install_plan(str(tmp_path), PY)

        assert commands == [[PY, "-m", "pip", "install", "-q", "-r", "requirements.txt"]]
        assert fingerprint

    def test_a_pyproject_project_is_installed_editable_with_its_dev_group(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)

        commands, fingerprint = _install_plan(str(tmp_path), PY)

        assert len(commands) == 1
        assert commands[0][:7] == [PY, "-m", "pip", "install", "-q", "-e", "."]
        assert "pytest>=8.0" in commands[0]
        assert "pytest-asyncio>=0.24" in commands[0]
        assert fingerprint

    def test_group_includes_are_left_out_not_crashed_on(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)

        commands, _ = _install_plan(str(tmp_path), PY)

        assert all(isinstance(arg, str) for arg in commands[0])
        assert not any("include-group" in arg for arg in commands[0])

    def test_optional_dependencies_extras_count_too(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "x"\nversion = "0"\n'
            '[project.optional-dependencies]\ntest = ["pytest", "httpx"]\n'
        )

        commands, _ = _install_plan(str(tmp_path), PY)

        assert "pytest" in commands[0] and "httpx" in commands[0]

    def test_the_lockfile_is_part_of_the_fingerprint(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)
        _, before = _install_plan(str(tmp_path), PY)
        (tmp_path / "uv.lock").write_text("version = 1\n")

        _, after = _install_plan(str(tmp_path), PY)

        assert before != after

    def test_nothing_declared_means_nothing_installed(self, tmp_path):
        assert _install_plan(str(tmp_path), PY) == ([], "")

    def test_a_broken_pyproject_installs_nothing_rather_than_raising(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project\nname = ")

        assert _install_plan(str(tmp_path), PY) == ([], "")


class TestDevDependencies:
    def test_groups_before_extras_and_no_duplicates(self):
        pyproject = {
            "dependency-groups": {"dev": ["pytest", "respx"]},
            "project": {"optional-dependencies": {"test": ["pytest", "httpx"]}},
        }

        assert _dev_dependencies(pyproject) == ["pytest", "respx", "httpx"]

    def test_missing_sections(self):
        assert _dev_dependencies({}) == []
        assert _dev_dependencies({"project": {}}) == []


class TestTheGateOnAPyprojectProject:
    async def test_installs_before_testing(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)
        claude = _FakeClaude()

        result = await run_quality_gates(
            {"task": {"number": 88}, "workspace": str(tmp_path), "claude": claude},
        )

        assert len(_pip_calls(claude)) == 1
        assert claude.commands[-1][-4:] == ["pytest", "tests/", "-v", "--tb=short"]
        assert result["tests_passed"] is True
        assert result["tests_unavailable"] == ""

    async def test_an_unchanged_project_is_not_reinstalled(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(THESWARM_PYPROJECT)
        _, fingerprint = _install_plan(str(tmp_path), PY)
        claude = _FakeClaude()

        await run_quality_gates({
            "task": {"number": 88}, "workspace": str(tmp_path), "claude": claude,
            "deps_fingerprint": fingerprint,
        })

        assert _pip_calls(claude) == []


class TestRunnerMissing:
    def test_the_two_spellings_pytest_uses(self):
        assert _test_runner_missing("/usr/local/bin/python3: No module named pytest")
        assert _test_runner_missing("ModuleNotFoundError: No module named 'pytest'")

    def test_a_red_test_is_not_a_missing_runner(self):
        assert _test_runner_missing("FAILED tests/test_x.py::test_y - AssertionError") == ""

    async def test_the_gate_reports_it_as_unavailable_not_failed(self, tmp_path):
        claude = _FakeClaude(test_output=f"{PY}: No module named pytest", exit_code=1)

        result = await run_quality_gates(
            {"task": {"number": 88}, "workspace": str(tmp_path), "claude": claude},
        )

        assert result["tests_passed"] is False
        assert "pytest is not installed" in result["tests_unavailable"]

    def test_no_repair_rounds_against_a_runner_that_never_ran(self):
        state = {
            "tests_passed": False,
            "tests_unavailable": "pytest is not installed for the target interpreter",
            "retry_count": 0, "max_dev_retries": 2,
        }

        assert _should_retry(state) == "check_pr"

    def test_a_genuine_failure_still_retries(self):
        state = {
            "tests_passed": False, "tests_unavailable": "",
            "retry_count": 0, "max_dev_retries": 2,
        }

        assert _should_retry(state) == "retry"


class TestNoTestsCollected:
    async def test_an_empty_suite_is_not_red(self, tmp_path):
        claude = _FakeClaude(test_output="no tests ran in 0.01s", exit_code=5)

        result = await run_quality_gates(
            {"task": {"number": 88}, "workspace": str(tmp_path), "claude": claude},
        )

        assert result["tests_passed"] is True
        assert result["tests_unavailable"] == ""


class TestSuiteTooLongForTheWorkspace:
    """TheSwarm's own suite outruns the iteration's test budget. That is a
    fact about the suite, not a red test — CI runs it in full."""

    async def test_a_timeout_is_reported_as_unavailable_not_failed(self, tmp_path):
        claude = _FakeClaude(
            test_output=f"Timed out after {TEST_RUN_TIMEOUT_SECONDS}s", exit_code=-1,
        )

        result = await run_quality_gates(
            {"task": {"number": 88}, "workspace": str(tmp_path), "claude": claude},
        )

        assert result["tests_passed"] is False
        assert "did not finish" in result["tests_unavailable"]
        assert str(TEST_RUN_TIMEOUT_SECONDS) in result["tests_unavailable"]

    def test_no_repair_rounds_after_a_timeout(self):
        state = {
            "tests_passed": False,
            "tests_unavailable": "the test suite did not finish within 120s in the workspace",
            "retry_count": 0, "max_dev_retries": 2,
        }

        assert _should_retry(state) == "check_pr"

    async def test_the_gate_uses_the_named_budget(self, tmp_path):
        seen = {}

        class _Claude:
            async def run_tests(self, workdir, command, *, timeout=300):
                if "pytest" in command:
                    seen["timeout"] = timeout
                return {"passed": True, "output": "ok", "exit_code": 0}

        await run_quality_gates(
            {"task": {"number": 1}, "workspace": str(tmp_path), "claude": _Claude()},
        )

        assert seen["timeout"] == TEST_RUN_TIMEOUT_SECONDS
