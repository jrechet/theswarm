"""Tests for theswarm.infrastructure.sandbox — LocalSandbox backend."""

from __future__ import annotations

import os

import pytest

from theswarm.infrastructure.sandbox import CommandResult, LocalSandbox


# ── LocalSandbox.run_command ──────────────────────────────────────


class TestLocalSandboxRunCommand:
    async def test_echo_captures_stdout(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["echo", "hello world"],
            cwd=str(tmp_path),
        )
        assert result.exit_code == 0
        assert "hello world" in result.stdout
        assert result.timed_out is False

    async def test_nonzero_exit_code(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["python3", "-c", "import sys; sys.exit(42)"],
            cwd=str(tmp_path),
        )
        assert result.exit_code == 42

    async def test_stderr_captured(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["python3", "-c", "import sys; sys.stderr.write('oops\\n')"],
            cwd=str(tmp_path),
        )
        assert "oops" in result.stderr

    async def test_command_not_found(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["__nonexistent_command_xyz__"],
            cwd=str(tmp_path),
        )
        assert result.exit_code == 127

    async def test_env_override(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["python3", "-c", "import os; print(os.environ['TEST_VAR_XYZ'])"],
            cwd=str(tmp_path),
            env={"TEST_VAR_XYZ": "sandbox_value"},
        )
        assert result.exit_code == 0
        assert "sandbox_value" in result.stdout

    async def test_cwd_is_respected(self, tmp_path: object) -> None:
        sandbox = LocalSandbox()
        result = await sandbox.run_command(
            ["python3", "-c", "import os; print(os.getcwd())"],
            cwd=str(tmp_path),
        )
        assert result.exit_code == 0
        assert str(tmp_path) in result.stdout


# ── LocalSandbox.upload_file / download_file ──────────────────────


class TestLocalSandboxFileCopy:
    async def test_upload_copies_file(self, tmp_path: object) -> None:
        src = os.path.join(str(tmp_path), "source.txt")
        dst = os.path.join(str(tmp_path), "dest.txt")
        with open(src, "w") as f:
            f.write("content")

        sandbox = LocalSandbox()
        await sandbox.upload_file(src, dst)

        with open(dst) as f:
            assert f.read() == "content"

    async def test_download_copies_file(self, tmp_path: object) -> None:
        remote = os.path.join(str(tmp_path), "remote.txt")
        local = os.path.join(str(tmp_path), "local.txt")
        with open(remote, "w") as f:
            f.write("remote_data")

        sandbox = LocalSandbox()
        await sandbox.download_file(remote, local)

        with open(local) as f:
            assert f.read() == "remote_data"

    async def test_same_path_is_noop(self, tmp_path: object) -> None:
        path = os.path.join(str(tmp_path), "same.txt")
        with open(path, "w") as f:
            f.write("data")

        sandbox = LocalSandbox()
        # Should not raise even though src == dst
        await sandbox.upload_file(path, path)
        await sandbox.download_file(path, path)


# ── LocalSandbox.cleanup ─────────────────────────────────────────


class TestLocalSandboxCleanup:
    async def test_cleanup_is_noop(self) -> None:
        sandbox = LocalSandbox()
        # Should not raise
        await sandbox.cleanup()


# ── CommandResult dataclass ───────────────────────────────────────


class TestCommandResult:
    def test_defaults(self) -> None:
        result = CommandResult(exit_code=0, stdout="ok", stderr="")
        assert result.timed_out is False

    def test_frozen(self) -> None:
        result = CommandResult(exit_code=0, stdout="", stderr="")
        with pytest.raises(AttributeError):
            result.exit_code = 1  # type: ignore[misc]
