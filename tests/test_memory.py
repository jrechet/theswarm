import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from theswarm.memory import (
    load_memory,
    append_to_memory,
    _insert_under_heading,
    CATEGORIES,
    MEMORY_PATH,
    _INITIAL_CONTENT
)

# Since pytest-asyncio is not available, we use this helper
def run_async(coro):
    return asyncio.run(coro)

def test_load_memory_success():
    github = AsyncMock()
    github.get_file_content.return_value = "some content"

    result = run_async(load_memory(github, ref="main"))

    assert result == "some content"
    github.get_file_content.assert_called_once_with(MEMORY_PATH, ref="main")

def test_load_memory_exception():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("File not found")

    result = run_async(load_memory(github))

    assert result == ""

def test_load_memory_ref_passing():
    github = AsyncMock()
    github.get_file_content.return_value = "content"

    run_async(load_memory(github, ref="develop"))

    github.get_file_content.assert_called_once_with(MEMORY_PATH, ref="develop")

def test_insert_under_heading_with_placeholder():
    content = "## Category A\n_(placeholder)\n\n## Category B"
    heading = "Category A"
    entry = "- Entry 1"

    result = _insert_under_heading(content, heading, entry)

    assert "## Category A" in result
    assert entry in result
    assert "_(placeholder)" not in result

def test_insert_under_heading_with_existing_entries():
    content = "## Category A\n- Entry 1\n\n## Category B"
    heading = "Category A"
    entry = "- Entry 2"

    result = _insert_under_heading(content, heading, entry)

    # Note: current implementation prepends the new entry
    assert "## Category A\n- Entry 2\n- Entry 1" in result

def test_insert_under_heading_not_found():
    content = "## Category B"
    heading = "Category A"
    entry = "- Entry 1"

    result = _insert_under_heading(content, heading, entry)

    assert result == content

def test_append_to_memory_initialization():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")
    github._repo_name = "test-repo"
    github.update_file = AsyncMock(return_value=True)

    category = CATEGORIES[0]
    entry = "New learning"
    agent_role = "developer"

    success = run_async(append_to_memory(github, category, entry, agent_role))

    assert success is True
    # Verify update_file was called with initialized content
    call_args = github.update_file.call_args
    assert call_args is not None
    updated_content = call_args[0][1] # second positional arg is content
    assert "# Agent Memory — test-repo" in updated_content
    assert f"## {category}" in updated_content
    assert entry in updated_content

def test_append_to_memory_existing():
    github = AsyncMock()
    github.get_file_content.return_value = "## Stack technique\n_(populated by agents after first cycle)\n"
    github.update_file = AsyncMock(return_value=True)

    success = run_async(append_to_memory(github, "Stack technique", "Python 3.12", "architect"))

    assert success is True
    call_args = github.update_file.call_args
    updated_content = call_args[0][1]
    assert "## Stack technique" in updated_content
    assert "- [" in updated_content
    assert "(architect) Python 3.12" in updated_content

def test_append_to_memory_invalid_category():
    github = AsyncMock()
    github.get_file_content.return_value = _INITIAL_CONTENT.format(repo="test")
    github.update_file = AsyncMock(return_value=True)

    # "Invalid" is not in CATEGORIES
    success = run_async(append_to_memory(github, "Invalid", "Some entry", "dev"))

    assert success is True
    call_args = github.update_file.call_args
    updated_content = call_args[0][1]
    # Should fall back to "Erreurs à éviter"
    assert "## Erreurs à éviter" in updated_content
    assert "Some entry" in updated_content

def test_append_to_memory_heading_missing_in_content():
    github = AsyncMock()
    github.get_file_content.return_value = "# Just a title"
    github.update_file = AsyncMock(return_value=True)

    success = run_async(append_to_memory(github, "Stack technique", "Entry", "dev"))

    assert success is True
    call_args = github.update_file.call_args
    updated_content = call_args[0][1]
    # Should append at the end
    assert "## Stack technique" in updated_content
    assert "Entry" in updated_content

def test_append_to_memory_github_failure():
    github = AsyncMock()
    github.get_file_content.return_value = "content"
    github.update_file = AsyncMock(side_effect=Exception("API error"))

    success = run_async(append_to_memory(github, CATEGORIES[0], "entry", "role"))

    assert success is False
