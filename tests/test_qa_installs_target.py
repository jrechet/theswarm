"""QA installs the target the same way the Dev does — issue #151.

Cycle 5b1da00155c2: the Dev answered ALREADY_SATISFIED and produced no PR,
so `run_quality_gates` (the only place that installed the target) never
ran. QA then ran pytest against a workspace with nothing installed, read
the instant "No module named pytest" failure as a vacuous 0/0 pass, and
waited out a full readiness timeout per launch for a server that had
already exited on `No module named theswarm`.

`agents.base.install_target` is now shared by both agents, and QA's
`run_unit_tests` runs it before pytest — a no-op when the fingerprint QA
was handed (e.g. by the Dev, earlier in the same cycle) hasn't changed.
"""

from __future__ import annotations

from theswarm.agents.base import _requirements_fingerprint
from theswarm.agents.qa import run_unit_tests


class _FakeClaude:
    def __init__(self, main_result=None) -> None:
        self.commands: list[list[str]] = []
        self.main_result = main_result or {
            "passed": True,
            "output": "1 passed in 0.1s",
            "exit_code": 0,
        }

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        if "pip" in command:
            return {"passed": True, "output": "", "exit_code": 0}
        if "pytest_cov" in command:
            return {"passed": False, "output": "No module named pytest_cov", "exit_code": 1}
        return self.main_result


def _workspace(tmp_path, contents="fastapi\n"):
    (tmp_path / "requirements.txt").write_text(contents)
    return str(tmp_path)


def _install_calls(claude: _FakeClaude) -> list[list[str]]:
    return [c for c in claude.commands if "pip" in c and "install" in c]


async def test_fresh_workspace_installs_before_pytest(tmp_path):
    claude = _FakeClaude()
    result = await run_unit_tests({"workspace": _workspace(tmp_path), "claude": claude})

    assert len(_install_calls(claude)) == 1
    assert result["deps_fingerprint"]
    # The install must happen before pytest runs, not after.
    pytest_index = next(i for i, c in enumerate(claude.commands) if "pytest" in c and "-m" in c)
    install_index = next(i for i, c in enumerate(claude.commands) if "pip" in c and "install" in c)
    assert install_index < pytest_index


async def test_unchanged_fingerprint_skips_reinstall(tmp_path):
    claude = _FakeClaude()
    workspace = _workspace(tmp_path)
    fingerprint = _requirements_fingerprint(str(tmp_path / "requirements.txt"))

    result = await run_unit_tests({
        "workspace": workspace,
        "claude": claude,
        "deps_fingerprint": fingerprint,
    })

    assert _install_calls(claude) == []
    assert result["deps_fingerprint"] == fingerprint
    assert result["tests_passed"] is True


async def test_no_toolchain_file_skips_install(tmp_path):
    claude = _FakeClaude()
    result = await run_unit_tests({"workspace": str(tmp_path), "claude": claude})

    assert _install_calls(claude) == []
    assert result["deps_fingerprint"] == ""


# ── not_run: a missing runner or an empty collection is not a 0/0 pass ──


async def test_missing_pytest_is_not_run_not_a_pass(tmp_path):
    claude = _FakeClaude(main_result={
        "passed": False,
        "output": "/usr/local/bin/python3: No module named pytest",
        "exit_code": 1,
    })

    result = await run_unit_tests({"workspace": str(tmp_path), "claude": claude})

    assert result["unit_tests_not_run_reason"] == "pytest is not installed for the target interpreter"
    assert result["test_counts"] == {"passed": 0, "failed": 0, "errors": 0, "total": 0}
    assert result["security_scan"]["coverage_status"] == "not_run"


async def test_no_tests_collected_is_not_run_not_a_pass(tmp_path):
    claude = _FakeClaude(main_result={
        "passed": False,
        "output": "no tests ran in 0.01s",
        "exit_code": 5,
    })

    result = await run_unit_tests({"workspace": str(tmp_path), "claude": claude})

    assert result["unit_tests_not_run_reason"] == "no tests collected in the workspace"
    assert result["test_counts"] == {"passed": 0, "failed": 0, "errors": 0, "total": 0}


async def test_real_zero_zero_without_pytest_missing_marker_is_not_a_special_case(tmp_path):
    """A genuine 0 passed / 0 failed with exit code 0 is left as a normal pass."""
    claude = _FakeClaude(main_result={
        "passed": True,
        "output": "no tests ran in 0.01s",
        "exit_code": 0,
    })

    result = await run_unit_tests({"workspace": str(tmp_path), "claude": claude})

    assert result["unit_tests_not_run_reason"] == ""
