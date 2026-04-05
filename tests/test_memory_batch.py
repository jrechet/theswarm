"""Tests for the memory batch writer (append_to_memory_batch).

The function expects entries as list[tuple[str, str, str]] — (category, entry, agent_role).
"""

from unittest.mock import AsyncMock

import pytest

from theswarm.memory import append_to_memory_batch, CATEGORIES


@pytest.mark.asyncio
async def test_memory_batch():
    github = AsyncMock()
    github._repo_name = "test-repo"

    github.get_file_content.return_value = """\
# Agent Memory — test-repo

## Stack technique
_(populated by agents after first cycle)_

## Conventions de code
_(populated by agents)_

## Erreurs à éviter
_(populated by agents)_

## Décisions architecturales
_(populated by agents)_
"""

    # Entries are tuples: (category, entry, agent_role)
    entries = [
        ("Erreurs à éviter", "Issue 1", "QA"),
        ("Stack technique", "Python 3.12", "QA"),
        ("Erreurs à éviter", "Issue 2", "TechLead"),
    ]

    success = await append_to_memory_batch(github, entries)
    assert success is True

    args, kwargs = github.update_file.call_args
    updated_content = args[1]

    assert "Issue 1" in updated_content
    assert "Python 3.12" in updated_content
    assert "Issue 2" in updated_content
    assert "(QA)" in updated_content
    assert "(TechLead)" in updated_content
    assert "## Erreurs à éviter" in updated_content
    assert "## Stack technique" in updated_content
