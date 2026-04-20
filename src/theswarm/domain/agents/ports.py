"""Ports for the Agents bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.agents.value_objects import LLMResponse


class LLMPort(Protocol):
    """Any LLM backend: Claude, Ollama, OpenAI."""

    async def generate(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 8192,
    ) -> LLMResponse: ...


class VCSPort(Protocol):
    """Version control operations on a repository."""

    async def get_issues(
        self, labels: list[str] | None = None, state: str = "open",
    ) -> list[dict]: ...

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None,
    ) -> dict: ...

    async def update_issue(
        self, number: int, labels: list[str] | None = None, state: str | None = None,
    ) -> None: ...

    async def get_pull_requests(self, state: str = "open") -> list[dict]: ...

    async def create_pull_request(
        self, title: str, body: str, head: str, base: str,
    ) -> dict: ...

    async def get_pr_diff(self, pr_number: int) -> str: ...

    async def submit_review(
        self, pr_number: int, body: str, event: str,
    ) -> None: ...

    async def merge_pr(
        self, pr_number: int, method: str = "squash",
    ) -> None: ...

    async def close_pr(self, pr_number: int) -> None: ...

    async def create_pr_comment(self, pr_number: int, body: str) -> None: ...

    async def delete_branch(self, branch: str) -> None: ...

    async def read_file(
        self, path: str, ref: str | None = None,
    ) -> str | None: ...

    async def update_file(
        self, path: str, content: str, message: str, branch: str,
    ) -> None: ...

    async def ensure_branch_protection(self, branch: str = "main") -> None: ...


class GitCLIPort(Protocol):
    """Local git CLI operations."""

    async def clone(self, url: str, dest: str) -> None: ...
    async def checkout(self, branch: str, create: bool = False, cwd: str = "") -> None: ...
    async def commit(self, message: str, cwd: str = "") -> bool: ...
    async def push(self, branch: str, cwd: str = "") -> None: ...
    async def diff_stat(self, base: str = "main", cwd: str = "") -> str: ...
    async def pull(self, cwd: str = "") -> None: ...
    async def cleanup(self, workspace: str) -> None: ...


class TestRunnerPort(Protocol):
    """Runs tests in a workspace."""

    async def run_tests(self, command: str, cwd: str, timeout: int = 120) -> tuple[bool, str]: ...
