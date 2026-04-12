"""Tests for the PO agent (src/theswarm/agents/po.py)."""

from __future__ import annotations

import pytest

from theswarm.agents.po import (
    _route_phase,
    build_po_graph,
    select_daily_issues,
    validate_demo,
    write_daily_plan,
    write_daily_report,
)


# ── build_po_graph ─────────────────────────────────────────────────────


def test_build_po_graph_returns_compiled_graph():
    graph = build_po_graph()
    assert callable(getattr(graph, "ainvoke", None))


# ── stub mode: morning ─────────────────────────────────────────────────


async def test_stub_mode_morning():
    graph = build_po_graph()
    result = await graph.ainvoke({"phase": "morning"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result.get("result", "")


# ── stub mode: evening ─────────────────────────────────────────────────


async def test_stub_mode_evening():
    graph = build_po_graph()
    result = await graph.ainvoke({"phase": "evening"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result.get("result", "")


# ── _route_phase ───────────────────────────────────────────────────────


def test_route_phase_evening():
    assert _route_phase({"phase": "evening"}) == "validate_demo"


def test_route_phase_morning():
    assert _route_phase({"phase": "morning"}) == "select_daily_issues"


def test_route_phase_default():
    # No phase defaults to morning
    assert _route_phase({}) == "select_daily_issues"


# ── select_daily_issues (stub) ────────────────────────────────────────


async def test_select_daily_issues_stub():
    result = await select_daily_issues({"github": None, "claude": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── write_daily_plan (stub) ───────────────────────────────────────────


async def test_write_daily_plan_stub_no_plan():
    result = await write_daily_plan({"daily_plan": "", "github": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


async def test_write_daily_plan_stub_no_github():
    result = await write_daily_plan({"daily_plan": "Some plan", "github": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── validate_demo (stub) ──────────────────────────────────────────────


async def test_validate_demo_stub():
    result = await validate_demo({"claude": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── write_daily_report (stub) ─────────────────────────────────────────


async def test_write_daily_report_stub_no_report():
    result = await write_daily_report({"daily_report": "", "github": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


async def test_write_daily_report_stub_no_github():
    result = await write_daily_report({"daily_report": "Report text", "github": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]
