"""Sprint B C3 — encrypted per-project secret storage (Fernet)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_MASTER_KEY_ENV = "SWARM_VAULT_MASTER_KEY"


class VaultError(RuntimeError):
    """Raised when the vault cannot be used (missing key, corrupt value)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_master_key() -> bytes:
    raw = os.getenv(_MASTER_KEY_ENV, "").strip()
    if not raw:
        raise VaultError(
            f"{_MASTER_KEY_ENV} not set — generate with "
            "`python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`",
        )
    return raw.encode()


class SqliteSecretVault:
    """Encrypted per-project secret storage (Fernet).

    - `set` / `get` / `delete` / `list_keys` round-trip plaintext via Fernet
    - `list_keys` never returns ciphertext or plaintext values
    - `rotate_master_key` re-encrypts every row atomically with a new key
    - master key read from env `SWARM_VAULT_MASTER_KEY`; fail-fast when used
      without a key configured
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        master_key: bytes | None = None,
    ) -> None:
        self._db = db
        # Defer key loading until first use so imports never crash the boot
        self._master_key = master_key
        self._fernet: Fernet | None = None

    def _get_fernet(self) -> Fernet:
        if self._fernet is not None:
            return self._fernet
        key = self._master_key or _load_master_key()
        try:
            self._fernet = Fernet(key)
        except Exception as e:  # noqa: BLE001
            raise VaultError(f"invalid master key: {e}") from e
        return self._fernet

    async def set(self, project_id: str, key_name: str, value: str) -> None:
        if not project_id or not key_name:
            raise ValueError("project_id and key_name are required")
        fernet = self._get_fernet()
        token = fernet.encrypt(value.encode("utf-8"))
        now = _now_iso()
        await self._db.execute(
            """INSERT INTO project_secrets (project_id, key_name, encrypted_value, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(project_id, key_name) DO UPDATE SET
                   encrypted_value = excluded.encrypted_value,
                   updated_at = excluded.updated_at""",
            (project_id, key_name, token, now, now),
        )
        await self._db.commit()

    async def get(self, project_id: str, key_name: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT encrypted_value FROM project_secrets WHERE project_id = ? AND key_name = ?",
            (project_id, key_name),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        fernet = self._get_fernet()
        try:
            return fernet.decrypt(row["encrypted_value"]).decode("utf-8")
        except InvalidToken as e:
            raise VaultError(
                f"failed to decrypt secret {project_id}/{key_name} — master key mismatch?",
            ) from e

    async def delete(self, project_id: str, key_name: str) -> bool:
        cursor = await self._db.execute(
            "DELETE FROM project_secrets WHERE project_id = ? AND key_name = ?",
            (project_id, key_name),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_keys(self, project_id: str) -> list[str]:
        """Return key names only — never the ciphertext or plaintext."""
        cursor = await self._db.execute(
            "SELECT key_name FROM project_secrets WHERE project_id = ? ORDER BY key_name",
            (project_id,),
        )
        rows = await cursor.fetchall()
        return [r["key_name"] for r in rows]

    async def rotate_master_key(self, new_key: bytes) -> None:
        """Re-encrypt every row with `new_key`. Rolls back on failure."""
        try:
            new_fernet = Fernet(new_key)
        except Exception as e:  # noqa: BLE001
            raise VaultError(f"invalid new master key: {e}") from e

        old_fernet = self._get_fernet()
        cursor = await self._db.execute(
            "SELECT project_id, key_name, encrypted_value FROM project_secrets",
        )
        rows = await cursor.fetchall()

        # Decrypt everything first, so we fail fast before mutating
        reencrypted: list[tuple[bytes, str, str]] = []
        for row in rows:
            try:
                plaintext = old_fernet.decrypt(row["encrypted_value"])
            except InvalidToken as e:
                raise VaultError(
                    f"cannot decrypt {row['project_id']}/{row['key_name']} with current key",
                ) from e
            reencrypted.append((
                new_fernet.encrypt(plaintext),
                row["project_id"],
                row["key_name"],
            ))

        now = _now_iso()
        try:
            for token, pid, kname in reencrypted:
                await self._db.execute(
                    """UPDATE project_secrets
                       SET encrypted_value = ?, updated_at = ?
                       WHERE project_id = ? AND key_name = ?""",
                    (token, now, pid, kname),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

        self._fernet = new_fernet
        self._master_key = new_key
