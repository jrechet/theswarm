"""Dependencies reinstall when requirements change, and only then.

Two prod failures shaped this. Reinstalling on every Ralph Loop retry ate
360s of the 480s phase budget (cycle 1d816463e34b). But a flat
"already installed" flag was wrong in the other direction: a retry that adds
a missing dependency needs it installed, and skipping that left the target's
tests failing on a module the retry had just declared (cycle 8170b32ca48f).
Keying on the file's content satisfies both.
"""

from __future__ import annotations

from theswarm.agents.dev import _requirements_fingerprint, run_quality_gates


class _FakeClaude:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        return {"passed": False, "output": "boom", "exit_code": 1}


def _workspace(tmp_path, contents="fastapi\n"):
    (tmp_path / "requirements.txt").write_text(contents)
    return str(tmp_path)


def _install_calls(claude: _FakeClaude) -> list[list[str]]:
    return [c for c in claude.commands if "pip" in c]


async def test_first_run_installs(tmp_path):
    claude = _FakeClaude()
    result = await run_quality_gates(
        {"task": {"number": 1}, "workspace": _workspace(tmp_path), "claude": claude},
    )

    assert len(_install_calls(claude)) == 1
    assert result["deps_fingerprint"]


async def test_retry_with_unchanged_requirements_skips_reinstall(tmp_path):
    claude = _FakeClaude()
    workspace = _workspace(tmp_path)
    fingerprint = _requirements_fingerprint(str(tmp_path / "requirements.txt"))

    result = await run_quality_gates({
        "task": {"number": 1},
        "workspace": workspace,
        "claude": claude,
        "deps_fingerprint": fingerprint,
    })

    assert _install_calls(claude) == []
    assert any("pytest" in c for c in claude.commands)  # tests still run
    assert result["deps_fingerprint"] == fingerprint


async def test_retry_that_adds_a_dependency_reinstalls(tmp_path):
    """The regression: a retry declaring httpx must actually install it."""
    claude = _FakeClaude()
    workspace = _workspace(tmp_path, "fastapi\n")
    stale = _requirements_fingerprint(str(tmp_path / "requirements.txt"))

    # The Ralph Loop retry adds the missing dependency
    (tmp_path / "requirements.txt").write_text("fastapi\nhttpx\n")

    result = await run_quality_gates({
        "task": {"number": 1},
        "workspace": workspace,
        "claude": claude,
        "deps_fingerprint": stale,
    })

    assert len(_install_calls(claude)) == 1
    assert result["deps_fingerprint"] != stale


async def test_no_requirements_file_skips_install(tmp_path):
    claude = _FakeClaude()
    result = await run_quality_gates(
        {"task": {"number": 1}, "workspace": str(tmp_path), "claude": claude},
    )

    assert _install_calls(claude) == []
    assert result["deps_fingerprint"] == ""


def test_fingerprint_tracks_content(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi\n")
    first = _requirements_fingerprint(str(req))

    req.write_text("fastapi\n")
    assert _requirements_fingerprint(str(req)) == first

    req.write_text("fastapi\nhttpx\n")
    assert _requirements_fingerprint(str(req)) != first


def test_fingerprint_of_missing_file_is_empty(tmp_path):
    assert _requirements_fingerprint(str(tmp_path / "nope.txt")) == ""


def test_deps_fingerprint_is_declared_in_state():
    from theswarm.config import AgentState

    assert "deps_fingerprint" in AgentState.__annotations__
