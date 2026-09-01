"""GitHub App identity: JWT, installation tokens, env export, vault."""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response

from theswarm.tools import github_app


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


@pytest.fixture()
def creds(rsa_keypair) -> github_app.GitHubAppCredentials:
    private_pem, _ = rsa_keypair
    return github_app.GitHubAppCredentials(
        app_id="12345", private_key_pem=private_pem,
        client_id="Iv1.abc", client_secret="shhh",
    )


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    github_app.reset_state()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_APP_PRIVATE_KEY", raising=False)
    yield
    github_app.reset_state()


class _FakeVault:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    async def set(self, project_id, key, value):
        self.data[(project_id, key)] = value

    async def get(self, project_id, key):
        return self.data.get((project_id, key))


def _mock_github(respx_mock, token="ghs_installation", expires_in=3600):
    respx_mock.get("https://api.github.com/app/installations").mock(
        return_value=Response(200, json=[{"id": 777}]),
    )
    expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in),
    )
    return respx_mock.post(
        "https://api.github.com/app/installations/777/access_tokens",
    ).mock(
        return_value=Response(
            201, json={"token": token, "expires_at": expires_at},
        ),
    )


# ── App JWT ────────────────────────────────────────────────────────────


def test_app_jwt_is_a_valid_rs256_token(creds, rsa_keypair):
    _, public_pem = rsa_keypair
    token = github_app.app_jwt(creds, now=1_700_000_000)
    claims = pyjwt.decode(
        token, public_pem, algorithms=["RS256"],
        options={"verify_exp": False},
    )
    assert claims["iss"] == "12345"
    assert claims["iat"] == 1_700_000_000 - 60      # clock-skew allowance
    assert claims["exp"] == 1_700_000_000 + 540     # under GitHub's 600s cap


# ── Installation tokens ────────────────────────────────────────────────


@respx.mock
async def test_installation_token_is_fetched_then_cached(creds, respx_mock):
    mint = _mock_github(respx_mock)
    github_app._credentials = creds
    github_app._credentials_loaded = True

    first = await github_app.installation_token()
    second = await github_app.installation_token()

    assert first == second == "ghs_installation"
    assert mint.call_count == 1  # the second call came from cache


@respx.mock
async def test_token_near_expiry_is_refreshed(creds, respx_mock):
    mint = _mock_github(respx_mock, expires_in=200)  # < 300s refresh margin
    github_app._credentials = creds
    github_app._credentials_loaded = True

    await github_app.installation_token()
    await github_app.installation_token()

    assert mint.call_count == 2


@respx.mock
async def test_no_installation_yields_none(creds, respx_mock):
    respx_mock.get("https://api.github.com/app/installations").mock(
        return_value=Response(200, json=[]),
    )
    github_app._credentials = creds
    github_app._credentials_loaded = True

    assert await github_app.installation_token() is None


async def test_no_credentials_yields_none():
    assert await github_app.installation_token() is None


# ── ensure_github_token: the single integration point ─────────────────


@respx.mock
async def test_ensure_exports_the_installation_token(
    creds, respx_mock, monkeypatch,
):
    _mock_github(respx_mock)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_static_old")
    github_app._credentials = creds
    github_app._credentials_loaded = True

    token = await github_app.ensure_github_token()

    assert token == "ghs_installation"
    import os
    assert os.environ["GITHUB_TOKEN"] == "ghs_installation"


async def test_ensure_without_app_passes_the_static_token_through(monkeypatch):
    """The rollback path: no App configured → GITHUB_TOKEN works as before."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_static")
    assert await github_app.ensure_github_token() == "ghp_static"


# ── Credential storage ─────────────────────────────────────────────────


async def test_vault_roundtrip(creds):
    vault = _FakeVault()
    github_app.configure(vault)
    await github_app.store_credentials(creds)

    github_app.reset_state()
    github_app.configure(vault)
    loaded = await github_app.load_credentials()

    assert loaded is not None
    assert loaded.app_id == "12345"
    assert loaded.private_key_pem == creds.private_key_pem


async def test_env_fallback_when_vault_is_empty(monkeypatch, rsa_keypair):
    private_pem, _ = rsa_keypair
    monkeypatch.setenv("GITHUB_APP_ID", "999")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", private_pem)
    github_app.configure(_FakeVault())

    loaded = await github_app.load_credentials()

    assert loaded is not None
    assert loaded.app_id == "999"


# ── Installation repositories (the V2 picker) ──────────────────────────


@respx.mock
async def test_installation_repositories_are_listed(creds, respx_mock):
    _mock_github(respx_mock)
    respx_mock.get(
        "https://api.github.com/installation/repositories?per_page=100",
    ).mock(return_value=Response(200, json={
        "repositories": [
            {"full_name": "jrechet/concert-tour-app", "private": False},
            {"full_name": "jrechet/theswarm", "private": False},
        ],
    }))
    github_app._credentials = creds
    github_app._credentials_loaded = True

    repos = await github_app.list_installation_repositories()

    assert [r["full_name"] for r in repos] == [
        "jrechet/concert-tour-app", "jrechet/theswarm",
    ]
