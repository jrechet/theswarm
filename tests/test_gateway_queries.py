"""Tests for theswarm.gateway.queries — read-only plan, report, issues."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from theswarm.gateway.queries import get_plan, get_report, list_issues


@pytest.fixture()
def gw():
    return MagicMock()


# ── get_plan ────────────────────────────────────────────────────────────


async def test_get_plan_no_vcs(gw):
    gw._swarm_po_github = None
    result = await get_plan(gw)
    assert result is None


async def test_get_plan_file_not_found(gw):
    vcs = MagicMock()
    vcs.get_file_content.side_effect = FileNotFoundError("not found")
    gw._swarm_po_github = vcs
    result = await get_plan(gw)
    assert result is None


# ── get_report ──────────────────────────────────────────────────────────


async def test_get_report_no_vcs(gw):
    gw._swarm_po_github = None
    result = await get_report(gw)
    assert result is None


# ── list_issues ─────────────────────────────────────────────────────────


async def test_list_issues_no_vcs(gw):
    gw._swarm_po_github = None
    result = await list_issues(gw)
    assert result == []


async def test_list_issues_exception(gw):
    vcs = MagicMock()
    vcs.list_issues.side_effect = RuntimeError("API error")
    gw._swarm_po_github = vcs
    result = await list_issues(gw)
    assert result == []
