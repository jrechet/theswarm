"""Memory writer — agents append learnings to AGENT_MEMORY.md in the target repo.

Each entry is categorized and timestamped. The Tech Lead reviews memory PRs
implicitly (entries go directly to main for the MVP).
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime

log = logging.getLogger(__name__)

MEMORY_PATH = "AGENT_MEMORY.md"

# Default initial content if AGENT_MEMORY.md doesn't exist yet
_INITIAL_CONTENT = """\
# Agent Memory — {repo}

Collective knowledge built by the SWARM team across dev cycles.

## Stack technique
_(populated by agents after first cycle)_

## Conventions de code
_(populated by agents)_

## Erreurs à éviter
_(populated by agents)_

## Décisions architecturales
_(populated by agents)_
"""

# Valid categories that agents can write to
CATEGORIES = [
    "Stack technique",
    "Conventions de code",
    "Erreurs à éviter",
    "Décisions architecturales",
]

_memory_lock = None

def _get_lock():
    global _memory_lock
    if _memory_lock is None:
        _memory_lock = asyncio.Lock()
    return _memory_lock


async def load_memory(github, ref: str = "main") -> str:
    """Load AGENT_MEMORY.md from the repo. Returns empty string if not found."""
    try:
        return await github.get_file_content(MEMORY_PATH, ref=ref)
    except Exception:
        return ""


async def append_to_memory_batch(
    github,
    entries: list[tuple[str, str, str]],
    branch: str = "main",
) -> bool:
    """Append multiple entries to AGENT_MEMORY.md.

    entries is a list of tuples: (category, entry, agent_role)
    Returns True if entries were added, False on error.
    """
    if not entries:
        return True

    async with _get_lock():
        current = await load_memory(github)
        if not current:
            # Initialize the file
            repo_name = getattr(github, '_repo_name', 'unknown')
            current = _INITIAL_CONTENT.format(repo=repo_name)

        timestamp = datetime.now().strftime("%Y-%m-%d")
        updated = current

        roles = set()
        categories = set()

        for category, entry, agent_role in entries:
            if category not in CATEGORIES:
                log.warning("Memory: unknown category '%s', using 'Erreurs à éviter'", category)
                category = "Erreurs à éviter"

            categories.add(category)
            roles.add(agent_role)
            formatted_entry = f"- [{timestamp}] ({agent_role}) {entry}"

            new_updated = _insert_under_heading(updated, category, formatted_entry)
            if new_updated == updated:
                log.warning("Memory: could not find heading '## %s', appending at end", category)
                new_updated = updated.rstrip() + f"\n\n## {category}\n{formatted_entry}\n"
            updated = new_updated

        if updated == current:
            return True

        cats_str = ", ".join(sorted(categories))
        roles_str = ", ".join(sorted(roles))
        try:
            await github.update_file(
                MEMORY_PATH,
                updated,
                branch=branch,
                commit_message=f"chore: update agent memory [{cats_str}] — {roles_str}",
            )
            log.info("Memory: appended %d entries by %s", len(entries), roles_str)
            return True
        except Exception:
            log.exception("Memory: failed to update %s", MEMORY_PATH)
            return False

async def append_to_memory(
    github,
    category: str,
    entry: str,
    agent_role: str,
    branch: str = "main",
) -> bool:
    """Append an entry to AGENT_MEMORY.md under the given category.

    Returns True if the entry was added, False on error.
    """
    return await append_to_memory_batch(
        github,
        [(category, entry, agent_role)],
        branch=branch,
    )


def _insert_under_heading(content: str, heading: str, entry: str) -> str:
    """Insert an entry under a ## heading, before the next ## or end of file."""
    marker = f"## {heading}"
    lines = content.split("\n")
    result = []
    inserted = False

    i = 0
    while i < len(lines):
        result.append(lines[i])

        if not inserted and lines[i].strip() == marker:
            # Found the heading — collect existing content under it
            i += 1
            # Skip blank lines and placeholder text right after heading
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith("_(")):
                if lines[i].startswith("_("):
                    i += 1  # skip placeholder
                    continue
                result.append(lines[i])
                i += 1

            # Insert before the next content or next heading
            result.append(entry)
            inserted = True
            continue

        i += 1

    if not inserted:
        return content  # heading not found, caller handles it

    return "\n".join(result)
