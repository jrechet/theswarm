"""Issue #49 — detect missing or invalid GitHub credentials for a repo.

Cheaper and more specific than letting a mid-cycle ``GithubException``
surface: distinguishes "nothing configured" from "a credential exists but
can't read this repo" (expired token vs. wrong scope/installation), so a
blocked cycle traces back to the actual fix.
"""

from __future__ import annotations

import os

from github import GithubException

from theswarm.tools import github_app
from theswarm.tools.github import GitHubClient


class RepoAccessError(RuntimeError):
    """Raised when the configured GitHub credential can't read a repo."""

    def __init__(self, repo: str, missing_credential: str, reason: str) -> None:
        super().__init__(reason)
        self.repo = repo
        self.missing_credential = missing_credential
        self.reason = reason


async def check_repo_access(repo_name: str) -> None:
    """Raise `RepoAccessError` unless `repo_name` is reachable right now."""
    app_creds = await github_app.load_credentials()
    static_token = os.environ.get("GITHUB_TOKEN", "")
    if app_creds is None and not static_token:
        raise RepoAccessError(
            repo_name,
            missing_credential="GITHUB_TOKEN / GitHub App credentials",
            reason=f"repo '{repo_name}': GITHUB_TOKEN is missing",
        )

    source = "GitHub App installation token" if app_creds is not None else "GITHUB_TOKEN"
    try:
        client = GitHubClient(repo_name)
        await client._fresh()
        await client._run(lambda: client._repo.full_name)
    except GithubException as exc:
        status = getattr(exc, "status", 0) or 0
        if status == 401:
            raise RepoAccessError(
                repo_name,
                missing_credential=source,
                reason=f"repo '{repo_name}': {source} is invalid or expired",
            ) from exc
        if status in (403, 404):
            if app_creds is not None:
                raise RepoAccessError(
                    repo_name,
                    missing_credential="GitHub App installation",
                    reason=(
                        f"repo '{repo_name}': GitHub App has no installation "
                        "covering this repo"
                    ),
                ) from exc
            raise RepoAccessError(
                repo_name,
                missing_credential=source,
                reason=f"repo '{repo_name}': {source} cannot read this repo",
            ) from exc
        raise RepoAccessError(
            repo_name,
            missing_credential=source,
            reason=f"repo '{repo_name}': {source} failed ({status or 'unknown error'})",
        ) from exc
