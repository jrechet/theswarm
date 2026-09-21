"""Tests for Issue #49 — RepoAccessGuard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from github import GithubException

from theswarm.application.services.repo_access_guard import (
    RepoAccessError,
    check_repo_access,
)
from theswarm.tools.github_app import GitHubAppCredentials

_APP_CREDS = GitHubAppCredentials(
    app_id="1", private_key_pem="key", client_id="cid", client_secret="secret"
)


def _mock_client(*, full_name: str = "org/name", side_effect=None) -> MagicMock:
    client = MagicMock()
    client._fresh = AsyncMock()
    if side_effect is not None:
        client._run = AsyncMock(side_effect=side_effect)
    else:
        client._run = AsyncMock(return_value=full_name)
    return client


class TestCheckRepoAccess:
    async def test_raises_when_no_credential_configured(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with patch(
            "theswarm.application.services.repo_access_guard.github_app.load_credentials",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.repo == "org/name"
        assert exc.value.missing_credential == "GITHUB_TOKEN / GitHub App credentials"
        assert exc.value.reason == "repo 'org/name': GITHUB_TOKEN is missing"

    async def test_returns_normally_when_repo_reachable(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_static")
        client = _mock_client()
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            await check_repo_access("org/name")  # no raise

        client._fresh.assert_awaited_once()
        client._run.assert_awaited_once()

    async def test_static_token_401_is_invalid_or_expired(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_bad")
        client = _mock_client(
            side_effect=GithubException(401, {"message": "Bad credentials"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GITHUB_TOKEN"
        assert exc.value.reason == "repo 'org/name': GITHUB_TOKEN is invalid or expired"
        assert isinstance(exc.value.__cause__, GithubException)

    async def test_static_token_404_cannot_read_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_scoped")
        client = _mock_client(
            side_effect=GithubException(404, {"message": "Not Found"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GITHUB_TOKEN"
        assert exc.value.reason == "repo 'org/name': GITHUB_TOKEN cannot read this repo"

    async def test_static_token_403_cannot_read_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_scoped")
        client = _mock_client(
            side_effect=GithubException(403, {"message": "Forbidden"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GITHUB_TOKEN"
        assert exc.value.reason == "repo 'org/name': GITHUB_TOKEN cannot read this repo"

    async def test_github_app_401_is_invalid_or_expired(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        client = _mock_client(
            side_effect=GithubException(401, {"message": "Bad credentials"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=_APP_CREDS),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GitHub App installation token"
        assert (
            exc.value.reason
            == "repo 'org/name': GitHub App installation token is invalid or expired"
        )

    async def test_github_app_404_has_no_installation(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        client = _mock_client(
            side_effect=GithubException(404, {"message": "Not Found"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=_APP_CREDS),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GitHub App installation"
        assert (
            exc.value.reason
            == "repo 'org/name': GitHub App has no installation covering this repo"
        )

    async def test_other_github_exception_status_reraised(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_static")
        client = _mock_client(
            side_effect=GithubException(500, {"message": "Server Error"}, None)
        )
        with (
            patch(
                "theswarm.application.services.repo_access_guard.github_app.load_credentials",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "theswarm.application.services.repo_access_guard.GitHubClient",
                return_value=client,
            ),
        ):
            with pytest.raises(RepoAccessError) as exc:
                await check_repo_access("org/name")

        assert exc.value.missing_credential == "GITHUB_TOKEN"
        assert "failed (500)" in exc.value.reason
