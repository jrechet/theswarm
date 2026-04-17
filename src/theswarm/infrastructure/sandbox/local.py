"""Local sandbox backend — runs commands directly on the host (current behavior)."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

from .protocol import CommandResult, SandboxBackend  # noqa: F401 (SandboxBackend for type-checking)

log = logging.getLogger(__name__)


class LocalSandbox:
    """Implements SandboxBackend by running commands locally via asyncio.subprocess."""

    async def run_command(
        self,
        command: list[str],
        *,
        cwd: str,
        timeout: int = 300,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Execute *command* as a subprocess, returning captured output."""
        merged_env: dict[str, str] | None = None
        if env is not None:
            merged_env = {**os.environ, **env}

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=merged_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore[union-attr]
            return CommandResult(
                exit_code=-1,
                stdout="",
                stderr="Command timed out",
                timed_out=True,
            )
        except FileNotFoundError as exc:
            return CommandResult(
                exit_code=127,
                stdout="",
                stderr=str(exc),
            )

        return CommandResult(
            exit_code=proc.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """Copy a local file to the 'remote' path (local copy for this backend)."""
        if local_path != remote_path:
            shutil.copy2(local_path, remote_path)

    async def download_file(self, remote_path: str, local_path: str) -> None:
        """Copy a 'remote' file to a local path (local copy for this backend)."""
        if remote_path != local_path:
            shutil.copy2(remote_path, local_path)

    async def cleanup(self) -> None:
        """Nothing to clean up for the local backend."""
