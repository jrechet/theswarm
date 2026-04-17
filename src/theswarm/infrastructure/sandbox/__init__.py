"""Sandbox execution abstraction — run commands in isolated environments."""

from __future__ import annotations

from .local import LocalSandbox
from .protocol import CommandResult, SandboxBackend

__all__ = ["CommandResult", "LocalSandbox", "SandboxBackend"]
