"""Sandbox execution protocol — abstraction for running commands in isolated environments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    """Result of a sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class SandboxBackend(Protocol):
    """Protocol for sandbox backends (local, Docker, remote, etc.)."""

    async def run_command(
        self,
        command: list[str],
        *,
        cwd: str,
        timeout: int = 300,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...

    async def upload_file(self, local_path: str, remote_path: str) -> None: ...

    async def download_file(self, remote_path: str, local_path: str) -> None: ...

    async def cleanup(self) -> None: ...
