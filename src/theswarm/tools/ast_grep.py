"""AST-Grep wrapper — structural code search for agents."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AstGrepMatch:
    """A single match returned by ``ast-grep``."""

    file: str
    line: int
    column: int
    text: str
    rule: str


async def is_available() -> bool:
    """Check if ast-grep (``sg``) binary is installed."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sg", "--version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return proc.returncode == 0
    except FileNotFoundError:
        return False


def _parse_matches(raw: str, *, rule: str = "") -> list[AstGrepMatch]:
    """Parse JSON output from ``sg`` into typed match objects."""
    if not raw.strip():
        return []

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Failed to parse ast-grep JSON output")
        return []

    matches: list[AstGrepMatch] = []
    for item in items:
        range_info = item.get("range", {}).get("start", {})
        matches.append(
            AstGrepMatch(
                file=item.get("file", ""),
                line=range_info.get("line", 0),
                column=range_info.get("column", 0),
                text=item.get("text", ""),
                rule=rule or item.get("ruleId", ""),
            )
        )
    return matches


async def search(
    pattern: str,
    path: str,
    *,
    lang: str = "python",
    timeout: int = 30,
) -> list[AstGrepMatch]:
    """Run ast-grep search on a directory.

    Returns matches or an empty list if ast-grep is not installed.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "sg", "--pattern", pattern, "--lang", lang, "--json", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except FileNotFoundError:
        log.warning("ast-grep (sg) not found — skipping structural search")
        return []
    except asyncio.TimeoutError:
        log.warning("ast-grep timed out after %ds", timeout)
        proc.kill()  # type: ignore[union-attr]
        return []

    if proc.returncode != 0:
        log.debug(
            "ast-grep exited %d: %s",
            proc.returncode,
            stderr.decode(errors="replace"),
        )

    return _parse_matches(stdout.decode(errors="replace"), rule=pattern)


async def check_patterns(
    path: str,
    rules: list[dict[str, str]],
    *,
    timeout: int = 60,
) -> list[AstGrepMatch]:
    """Run multiple ast-grep rules against a codebase.

    Each rule dict should contain ``pattern`` and optionally ``lang``
    (defaults to ``"python"``).
    """
    all_matches: list[AstGrepMatch] = []
    for rule in rules:
        pattern = rule.get("pattern", "")
        lang = rule.get("lang", "python")
        if not pattern:
            continue
        matches = await search(pattern, path, lang=lang, timeout=timeout)
        all_matches.extend(matches)
    return all_matches
