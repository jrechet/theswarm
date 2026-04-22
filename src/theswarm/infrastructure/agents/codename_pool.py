"""Codename pool loader and deterministic picker.

The pool lives at ``data/codenames.yaml`` and is expected to be a moderately
large, culturally diverse list of short first names. The picker is
**deterministic** for reproducibility (same project + role + pool snapshot
→ same candidate order) but skips codenames already in use.

Public entry points:

- ``load_pool(path=None) -> tuple[str, ...]``
- ``pick_codename(project_id, role, pool, in_use) -> str``
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


class CodenameExhausted(RuntimeError):
    """All codenames in the pool are already in use."""


_PACKAGED_POOL_PATH = Path(__file__).resolve().parent / "codenames.yaml"
_REPO_ROOT_POOL_PATH = Path(__file__).resolve().parents[4] / "data" / "codenames.yaml"


def _resolve_default_pool_path() -> Path:
    """Pick the best available pool path (packaged > repo-root)."""
    if _PACKAGED_POOL_PATH.exists():
        return _PACKAGED_POOL_PATH
    return _REPO_ROOT_POOL_PATH


def load_pool(path: Path | str | None = None) -> tuple[str, ...]:
    """Load the codename list from YAML. Dedupes while preserving order."""
    source = Path(path) if path else _resolve_default_pool_path()
    if not source.exists():
        return ()
    with source.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    names = data.get("names") or []
    seen: set[str] = set()
    unique: list[str] = []
    for raw in names:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return tuple(unique)


def pick_codename(
    project_id: str,
    role: str,
    pool: tuple[str, ...],
    in_use: set[str] | frozenset[str],
) -> str:
    """Pick the first available codename for (project_id, role).

    Deterministic: uses a stable hash of ``project_id + role`` to pick a
    starting offset into the pool, then walks forward skipping any codename
    already in use. This way re-running creation with the same inputs lands on
    the same name until the pool drifts.
    """
    if not pool:
        raise CodenameExhausted("Codename pool is empty — check data/codenames.yaml")

    key = f"{project_id}::{role}".encode("utf-8")
    offset = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % len(pool)

    for step in range(len(pool)):
        candidate = pool[(offset + step) % len(pool)]
        if candidate not in in_use:
            return candidate

    raise CodenameExhausted(
        f"All {len(pool)} codenames are in use — add more to data/codenames.yaml",
    )
