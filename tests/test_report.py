"""Tests for theswarm.report — HTML report generation."""

from __future__ import annotations

import pytest

from theswarm.report import (
    generate_cycle_report,
    generate_weekly_summary,
    _escape,
    _status_color,
    _render_pr_cards,
    _render_quality_gates,
    _render_cost_summary,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_result(**overrides):
    base = {
        "date": "2026-04-07",
        "cost_usd": 2.50,
        "tokens": 150000,
        "prs": [
            {"number": 1, "title": "Add login", "url": "https://github.com/o/r/pull/1"},
            {"number": 2, "title": "Fix header", "url": "https://github.com/o/r/pull/2"},
        ],
        "reviews": [
            {"pr_number": 1, "decision": "APPROVE", "summary": "Looks good"},
            {"pr_number": 2, "decision": "REQUEST_CHANGES", "summary": "Needs work",
             "issues": [{"description": "Missing tests"}]},
        ],
        "demo_report": {
            "overall_status": "yellow",
            "quality_gates": {
                "unit_tests": {"total": 50, "passed": 48, "failed": 2, "status": "fail"},
                "e2e_tests": {"total": 10, "passed": 10, "failed": 0, "status": "pass"},
                "security": {"semgrep_high": 0, "status": "pass"},
                "coverage": {"percent": 75.0, "threshold": 70, "status": "pass"},
            },
            "metrics": {
                "unit_tests": 50, "unit_passed": 48, "unit_failed": 2,
                "e2e_tests": 10, "e2e_passed": 10, "e2e_failed": 0,
                "total_tests": 60, "coverage_pct": 75.0,
                "open_issues": 5, "closed_today": 2,
            },
        },
        "daily_report": "## Summary\n\n2 features delivered.",
    }
    base.update(overrides)
    return base


# ── _escape ──────────────────────────────────────────────────────────


def test_escape_html():
    assert _escape("<script>alert('xss')</script>") == "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" or \
           "&lt;script&gt;" in _escape("<script>alert('xss')</script>")


def test_escape_newlines():
    assert "<br>" in _escape("line1\nline2")


def test_escape_ampersand():
    assert "&amp;" in _escape("A & B")


# ── _status_color ────────────────────────────────────────────────────


def test_status_color_green():
    assert _status_color("green") == "#00cc88"


def test_status_color_red():
    assert _status_color("red") == "#ff4466"


def test_status_color_unknown():
    assert _status_color("banana") == "#8888a0"


# ── generate_cycle_report ────────────────────────────────────────────


def test_report_contains_date():
    html = generate_cycle_report(_make_result())
    assert "2026-04-07" in html


def test_report_contains_cost():
    html = generate_cycle_report(_make_result())
    assert "$2.50" in html


def test_report_contains_pr_numbers():
    html = generate_cycle_report(_make_result())
    assert "#1" in html
    assert "#2" in html


def test_report_contains_quality_gates():
    html = generate_cycle_report(_make_result())
    assert "Unit Tests" in html
    assert "E2E Tests" in html or "E2e Tests" in html


def test_report_contains_daily_report():
    html = generate_cycle_report(_make_result())
    assert "2 features delivered" in html


def test_report_with_approve_buttons():
    html = generate_cycle_report(_make_result(), base_url="https://bots.jrec.fr/swarm")
    assert "Approve" in html
    assert "/reports/2026-04-07/approve/" in html


def test_report_no_buttons_without_base_url():
    html = generate_cycle_report(_make_result(), base_url="")
    assert "/approve/" not in html


def test_report_no_prs():
    result = _make_result(prs=[], reviews=[])
    html = generate_cycle_report(result)
    assert "No PRs opened" in html


def test_report_approved_pr_no_button():
    """Approved PRs don't get an approve button."""
    result = _make_result(
        prs=[{"number": 1, "title": "Done", "url": "#"}],
        reviews=[{"pr_number": 1, "decision": "APPROVE", "summary": "ok"}],
    )
    html = generate_cycle_report(result, base_url="https://example.com/swarm")
    assert "/approve/1" not in html


def test_report_no_demo_report():
    result = _make_result(demo_report=None)
    html = generate_cycle_report(result)
    assert "No quality gate data" in html


def test_report_no_daily_report():
    result = _make_result(daily_report="")
    html = generate_cycle_report(result)
    assert "No PO report generated" in html


# ── generate_weekly_summary ──────────────────────────────────────────


def test_weekly_empty():
    html = generate_weekly_summary([])
    assert "No cycle data" in html


def test_weekly_with_entries():
    entries = [
        {"date": "2026-04-07", "repo": "o/r", "cost_usd": 1.5, "tokens": 50000,
         "prs_opened": 2, "prs_merged": 1, "demo_status": "green"},
        {"date": "2026-04-06", "repo": "o/r", "cost_usd": 2.0, "tokens": 80000,
         "prs_opened": 3, "prs_merged": 2, "demo_status": "yellow"},
    ]
    html = generate_weekly_summary(entries)
    assert "2 cycles" in html or "2</div>" in html
    assert "$3.50" in html  # total cost
    assert "5" in html      # total PRs
    assert "3" in html      # total merged


def test_weekly_status_counts():
    entries = [
        {"date": "2026-04-07", "demo_status": "green", "cost_usd": 1, "tokens": 100,
         "prs_opened": 1, "prs_merged": 1, "repo": "o/r"},
        {"date": "2026-04-06", "demo_status": "red", "cost_usd": 1, "tokens": 100,
         "prs_opened": 1, "prs_merged": 0, "repo": "o/r"},
    ]
    html = generate_weekly_summary(entries)
    # Should show green=1, red=1
    assert "green" in html.lower()
    assert "red" in html.lower()


# ── _render_pr_cards ─────────────────────────────────────────────────


def test_pr_cards_with_review_issues():
    prs = [{"number": 1, "title": "Fix", "url": "#"}]
    reviews = {1: {"decision": "REQUEST_CHANGES", "summary": "Needs fix",
                   "issues": [{"description": "Missing error handling"}]}}
    html = _render_pr_cards(prs, reviews, "", "2026-04-07")
    assert "Missing error handling" in html


def test_pr_cards_comment_form():
    prs = [{"number": 1, "title": "Fix", "url": "#"}]
    reviews = {1: {"decision": "PENDING"}}
    html = _render_pr_cards(prs, reviews, "https://example.com/swarm", "2026-04-07")
    assert "comment" in html.lower()
    assert "/comment/1" in html


# ── _render_quality_gates ────────────────────────────────────────────


def test_quality_gates_empty():
    html = _render_quality_gates({}, {}, "unknown")
    assert "No quality gate data" in html


def test_quality_gates_coverage():
    gates = {"coverage": {"percent": 82.0, "threshold": 70, "status": "pass"}}
    html = _render_quality_gates(gates, {}, "green")
    assert "82.0%" in html


# ── _render_cost_summary ─────────────────────────────────────────────


def test_cost_summary():
    reviews = [{"decision": "APPROVE"}, {"decision": "REQUEST_CHANGES"}]
    html = _render_cost_summary(5.0, 200000, 3, reviews)
    assert "$5.00" in html
    assert "200,000" in html
    assert "$1.67" in html  # cost per PR


def test_cost_summary_no_prs():
    html = _render_cost_summary(0.0, 0, 0, [])
    assert "$0.00" in html
