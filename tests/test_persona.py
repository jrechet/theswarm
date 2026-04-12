"""Tests for theswarm.persona — handle_dm intent routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm_common.chat import Intent
from theswarm.persona import handle_dm


@pytest.fixture()
def chat():
    return AsyncMock()


@pytest.fixture()
def nlu():
    return AsyncMock()


@pytest.fixture()
def gw():
    g = MagicMock()
    g._swarm_po_vcs_map = {"owner/repo": MagicMock()}
    g._swarm_po_default_repo = "owner/repo"
    return g


# ── help ────────────────────────────────────────────────────────────────


async def test_handle_dm_help(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="help", confidence=0.9, params={}, raw_text="help")
    )
    await handle_dm("help", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "TheSwarm" in body


# ── low confidence ──────────────────────────────────────────────────────


async def test_handle_dm_low_confidence(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="unknown", confidence=0.1, params={}, raw_text="qwerty")
    )
    await handle_dm("qwerty", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "pas compris" in body


# ── show_status (idle) ──────────────────────────────────────────────────


async def test_handle_dm_show_status_idle(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="show_status", confidence=0.95, params={}, raw_text="status")
    )
    gw.swarm_po_is_cycle_running.return_value = False
    await handle_dm("status", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "Idle" in body


# ── show_status (running) ──────────────────────────────────────────────


async def test_handle_dm_show_status_running(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="show_status", confidence=0.95, params={}, raw_text="status")
    )
    gw.swarm_po_is_cycle_running.return_value = True
    gw.swarm_po_current_phase.return_value = "Dev: implementing"
    await handle_dm("status", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "Cycle en cours" in body


# ── show_plan (exists) ──────────────────────────────────────────────────


async def test_handle_dm_show_plan_exists(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="show_plan", confidence=0.9, params={}, raw_text="plan")
    )
    gw.swarm_po_get_plan = AsyncMock(return_value="## Plan\n- Task 1")
    await handle_dm("plan", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "Today's Plan" in body
    assert "Task 1" in body


# ── show_plan (none) ────────────────────────────────────────────────────


async def test_handle_dm_show_plan_none(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="show_plan", confidence=0.9, params={}, raw_text="plan")
    )
    gw.swarm_po_get_plan = AsyncMock(return_value=None)
    await handle_dm("plan", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "No plan found" in body


# ── show_report ─────────────────────────────────────────────────────────


async def test_handle_dm_show_report(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="show_report", confidence=0.9, params={}, raw_text="rapport")
    )
    gw.swarm_po_get_report = AsyncMock(return_value="All green.")
    await handle_dm("rapport", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "Latest Report" in body
    assert "All green." in body


# ── list_repos (repos exist) ───────────────────────────────────────────


async def test_handle_dm_list_repos(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="list_repos", confidence=0.9, params={}, raw_text="repos")
    )
    await handle_dm("repos", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "owner/repo" in body
    assert "Allowed Repositories" in body


# ── list_repos (none) ──────────────────────────────────────────────────


async def test_handle_dm_list_repos_empty(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="list_repos", confidence=0.9, params={}, raw_text="repos")
    )
    gw._swarm_po_vcs_map = {}
    await handle_dm("repos", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "No repositories configured" in body


# ── list_stories (issues exist) ────────────────────────────────────────


async def test_handle_dm_list_stories(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="list_stories", confidence=0.9, params={}, raw_text="backlog")
    )
    gw.swarm_po_list_issues = AsyncMock(
        return_value=[
            {"number": 42, "title": "Add login page", "labels": [{"name": "status:ready"}]},
        ]
    )
    await handle_dm("backlog", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "#42" in body
    assert "Add login page" in body


# ── list_stories (none) ────────────────────────────────────────────────


async def test_handle_dm_list_stories_empty(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="list_stories", confidence=0.9, params={}, raw_text="backlog")
    )
    gw.swarm_po_list_issues = AsyncMock(return_value=[])
    await handle_dm("backlog", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "No open issues" in body


# ── run_cycle (not running) ────────────────────────────────────────────


async def test_handle_dm_run_cycle(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="run_cycle", confidence=0.9, params={}, raw_text="go")
    )
    gw.swarm_po_is_cycle_running.return_value = False
    gw.run_swarm_cycle = AsyncMock()

    with patch("theswarm.persona.asyncio.create_task") as mock_create_task:
        await handle_dm("go", "u1", chat, nlu, gw)
        mock_create_task.assert_called_once()
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "Launching" in body


# ── run_cycle (already running) ────────────────────────────────────────


async def test_handle_dm_run_cycle_already_running(chat, nlu, gw):
    nlu.parse_intent = AsyncMock(
        return_value=Intent(action="run_cycle", confidence=0.9, params={}, raw_text="go")
    )
    gw.swarm_po_is_cycle_running.return_value = True
    gw.swarm_po_current_phase.return_value = "Dev: coding"
    await handle_dm("go", "u1", chat, nlu, gw)
    chat.post_dm.assert_called_once()
    body = chat.post_dm.call_args[0][1]
    assert "already running" in body
