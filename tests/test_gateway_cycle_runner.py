"""Tests for theswarm.gateway.cycle_runner — run_swarm_cycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.gateway.cycle_runner import run_swarm_cycle


@pytest.fixture()
def gw():
    g = MagicMock()
    g._swarm_po_chat = AsyncMock()
    g._swarm_po_team_chat = None
    g._swarm_po_config = MagicMock(team_channel="swarm-team")
    g._swarm_po_default_repo = "owner/repo"
    g._swarm_po_vcs_map = {"owner/repo": MagicMock()}
    g._swarm_po_cycle_running = False
    g._swarm_po_current_phase = ""
    return g


def _patch_dashboard():
    dash = MagicMock()
    return patch(
        "theswarm.dashboard.get_dashboard_state", return_value=dash
    )


# ── no repo and no default ──────────────────────────────────────────────


async def test_no_repo_no_default(gw):
    gw._swarm_po_default_repo = ""
    with _patch_dashboard():
        await run_swarm_cycle(gw, "u1", "")
    gw._swarm_po_chat.post_dm.assert_called_once()
    body = gw._swarm_po_chat.post_dm.call_args[0][1]
    assert "No repo specified" in body


# ── repo not in allowed list ────────────────────────────────────────────


async def test_repo_not_allowed(gw):
    with _patch_dashboard():
        await run_swarm_cycle(gw, "u1", "other/repo")
    gw._swarm_po_chat.post_dm.assert_called_once()
    body = gw._swarm_po_chat.post_dm.call_args[0][1]
    assert "not in allowed list" in body
    assert "owner/repo" in body


# ── success ─────────────────────────────────────────────────────────────


async def test_success(gw):
    result = {
        "daily_report": "All tasks done.",
        "cost_usd": 1.23,
        "prs": [{"number": 1}],
    }
    with (
        _patch_dashboard(),
        patch(
            "theswarm.cycle.run_daily_cycle",
            new_callable=AsyncMock,
            return_value=result,
        ),
        patch("theswarm.config.CycleConfig"),
    ):
        await run_swarm_cycle(gw, "u1", "owner/repo")

    assert gw._swarm_po_cycle_running is False
    gw._swarm_po_chat.post_dm.assert_called_once()
    body = gw._swarm_po_chat.post_dm.call_args[0][1]
    assert "Cycle terminé" in body
    assert "$1.23" in body
    assert "All tasks done." in body


# ── transient error then success ────────────────────────────────────────


async def test_transient_retry(gw):
    result = {"daily_report": "", "cost_usd": 0, "prs": []}
    call_count = 0

    async def side_effect(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise TimeoutError("connection timeout")
        return result

    with (
        _patch_dashboard(),
        patch(
            "theswarm.cycle.run_daily_cycle",
            new_callable=AsyncMock,
            side_effect=side_effect,
        ),
        patch("theswarm.config.CycleConfig"),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        await run_swarm_cycle(gw, "u1", "owner/repo")

    assert call_count == 2
    assert gw._swarm_po_cycle_running is False
    # Should have retry message + success message
    calls = gw._swarm_po_chat.post_dm.call_args_list
    assert len(calls) == 2
    assert "transitoire" in calls[0][0][1]
    assert "Cycle terminé" in calls[1][0][1]


# ── non-transient error ─────────────────────────────────────────────────


async def test_non_transient_error(gw):
    with (
        _patch_dashboard(),
        patch(
            "theswarm.cycle.run_daily_cycle",
            new_callable=AsyncMock,
            side_effect=ValueError("bad config"),
        ),
        patch("theswarm.config.CycleConfig"),
    ):
        await run_swarm_cycle(gw, "u1", "owner/repo")

    assert gw._swarm_po_cycle_running is False
    gw._swarm_po_chat.post_dm.assert_called_once()
    body = gw._swarm_po_chat.post_dm.call_args[0][1]
    assert "Cycle échoué" in body
    assert "ValueError" in body
