"""Tests for Sprint B C3 — SqliteSecretVault."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from theswarm.infrastructure.persistence.secret_vault import (
    SqliteSecretVault,
    VaultError,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "v.db"))
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def key() -> bytes:
    return Fernet.generate_key()


class TestSqliteSecretVault:
    async def test_set_get_round_trip(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("proj", "API_KEY", "s3cret-v4lue")
        assert await vault.get("proj", "API_KEY") == "s3cret-v4lue"

    async def test_set_overwrites(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("proj", "API_KEY", "first")
        await vault.set("proj", "API_KEY", "second")
        assert await vault.get("proj", "API_KEY") == "second"

    async def test_get_missing_returns_none(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        assert await vault.get("proj", "NOPE") is None

    async def test_delete(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("proj", "K", "v")
        assert await vault.delete("proj", "K") is True
        assert await vault.get("proj", "K") is None
        assert await vault.delete("proj", "K") is False

    async def test_list_keys_returns_names_only(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("proj", "A", "alpha")
        await vault.set("proj", "B", "beta")
        await vault.set("other", "C", "gamma")
        keys = await vault.list_keys("proj")
        assert keys == ["A", "B"]
        # Make sure no plaintext leaked into the listing
        for k in keys:
            assert "alpha" not in k and "beta" not in k

    async def test_empty_project_or_key_rejected(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        with pytest.raises(ValueError):
            await vault.set("", "K", "v")
        with pytest.raises(ValueError):
            await vault.set("p", "", "v")

    async def test_missing_master_key_fails_fast(self, db, monkeypatch):
        monkeypatch.delenv("SWARM_VAULT_MASTER_KEY", raising=False)
        vault = SqliteSecretVault(db)
        with pytest.raises(VaultError, match="SWARM_VAULT_MASTER_KEY"):
            await vault.set("p", "K", "v")

    async def test_vault_unused_without_key_is_safe(self, db, monkeypatch):
        # Construction alone must not require a key — only first use does
        monkeypatch.delenv("SWARM_VAULT_MASTER_KEY", raising=False)
        SqliteSecretVault(db)

    async def test_rotation_preserves_values(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("p", "A", "alpha")
        await vault.set("p", "B", "beta")

        new_key = Fernet.generate_key()
        await vault.rotate_master_key(new_key)

        assert await vault.get("p", "A") == "alpha"
        assert await vault.get("p", "B") == "beta"

    async def test_rotation_with_wrong_old_key_fails(self, db, key):
        vault = SqliteSecretVault(db, master_key=key)
        await vault.set("p", "A", "alpha")

        # Swap in a different "current" key — rotation should fail
        wrong_vault = SqliteSecretVault(db, master_key=Fernet.generate_key())
        with pytest.raises(VaultError):
            await wrong_vault.rotate_master_key(Fernet.generate_key())

        # Original key still decrypts fine
        assert await vault.get("p", "A") == "alpha"
