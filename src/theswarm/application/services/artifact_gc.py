"""Garbage-collect orphaned artifact directories.

An artifact dir is "orphaned" when its cycle_id has no matching row in the
reports table. This can happen when demos are deleted/expire but on-disk
bytes linger in ``~/.swarm-data/artifacts/{cycle_id}/``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class GCResult:
    scanned_dirs: int
    live_cycle_ids: int
    orphaned_dirs: tuple[str, ...]
    bytes_reclaimed: int
    deleted: bool


async def collect_live_cycle_ids(conn: aiosqlite.Connection) -> set[str]:
    cursor = await conn.execute("SELECT DISTINCT cycle_id FROM reports")
    rows = await cursor.fetchall()
    return {row[0] for row in rows if row[0]}


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


async def gc_artifacts(
    conn: aiosqlite.Connection,
    artifact_dir: str,
    *,
    dry_run: bool = True,
) -> GCResult:
    """Scan ``artifact_dir`` for cycle_id directories not referenced by any report.

    When ``dry_run`` is True (default), only reports what would be deleted.
    """
    live = await collect_live_cycle_ids(conn)
    base = Path(artifact_dir)

    if not base.is_dir():
        return GCResult(
            scanned_dirs=0,
            live_cycle_ids=len(live),
            orphaned_dirs=(),
            bytes_reclaimed=0,
            deleted=not dry_run,
        )

    orphaned: list[str] = []
    bytes_total = 0
    scanned = 0

    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        scanned += 1
        if child.name in live:
            continue
        size = _dir_size(child)
        bytes_total += size
        orphaned.append(child.name)
        if not dry_run:
            shutil.rmtree(child, ignore_errors=True)

    return GCResult(
        scanned_dirs=scanned,
        live_cycle_ids=len(live),
        orphaned_dirs=tuple(orphaned),
        bytes_reclaimed=bytes_total,
        deleted=not dry_run,
    )
