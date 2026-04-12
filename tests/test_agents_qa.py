"""Tests for the QA agent (src/theswarm/agents/qa.py)."""

from __future__ import annotations

import pytest

from theswarm.agents.qa import (
    _extract_python_code,
    _parse_pytest_summary,
    build_qa_graph,
    collect_issue_status,
    generate_demo_report,
    run_e2e_tests,
    run_security_scan,
    run_unit_tests,
    write_e2e_tests,
)


# ── build_qa_graph ─────────────────────────────────────────────────────


def test_build_qa_graph_returns_compiled_graph():
    graph = build_qa_graph()
    assert callable(getattr(graph, "ainvoke", None))


# ── stub mode graph invocation ────────────────────────────────────────


async def test_stub_mode_returns_demo_report():
    graph = build_qa_graph()
    result = await graph.ainvoke({"phase": "demo"})
    assert "demo_report" in result
    assert result["demo_report"] is not None
    assert "date" in result["demo_report"]
    assert "overall_status" in result["demo_report"]


# ── _parse_pytest_summary ──────────────────────────────────────────────


def test_parse_pytest_summary_all_pass():
    output = "===== 35 passed in 10.73s ====="
    counts = _parse_pytest_summary(output)
    assert counts["passed"] == 35
    assert counts["failed"] == 0
    assert counts["errors"] == 0
    assert counts["total"] == 35


def test_parse_pytest_summary_mixed():
    output = "===== 10 passed, 2 failed, 1 error in 5.12s ====="
    counts = _parse_pytest_summary(output)
    assert counts["passed"] == 10
    assert counts["failed"] == 2
    assert counts["errors"] == 1
    assert counts["total"] == 13


def test_parse_pytest_summary_no_tests():
    output = "no tests ran"
    counts = _parse_pytest_summary(output)
    assert counts["total"] == 0


def test_parse_pytest_summary_only_failed():
    output = "===== 3 failed in 2.50s ====="
    counts = _parse_pytest_summary(output)
    assert counts["passed"] == 0
    assert counts["failed"] == 3
    assert counts["total"] == 3


# ── _extract_python_code ──────────────────────────────────────────────


def test_extract_python_code_import_first():
    text = "import pytest\n\ndef test_foo():\n    assert True"
    result = _extract_python_code(text)
    assert result is not None
    assert result.startswith("import pytest")


def test_extract_python_code_markdown_fenced():
    text = "```python\nimport os\nprint(os.getcwd())\n```"
    result = _extract_python_code(text)
    assert result is not None
    assert "import os" in result


def test_extract_python_code_embedded_in_prose():
    text = "Here is the code:\n\nSome intro text.\nimport pytest\n\ndef test_it():\n    pass"
    result = _extract_python_code(text)
    assert result is not None
    assert result.startswith("import pytest")


def test_extract_python_code_no_code():
    text = "This is just plain text with no Python code."
    result = _extract_python_code(text)
    assert result is None


# ── generate_demo_report ──────────────────────────────────────────────


async def test_generate_demo_report_all_pass():
    state = {
        "test_counts": {"passed": 10, "failed": 0, "errors": 0, "total": 10},
        "tests_passed": True,
        "e2e_counts": {"passed": 5, "failed": 0, "errors": 0, "total": 5},
        "e2e_passed": True,
        "issue_stats": {"open": 2, "closed_today": 3},
        "security_scan": {
            "semgrep_high": 0,
            "semgrep_status": "pass",
            "coverage_pct": 85.0,
            "coverage_status": "pass",
        },
    }
    result = await generate_demo_report(state)
    report = result["demo_report"]
    assert report["overall_status"] == "green"
    assert report["metrics"]["unit_tests"] == 10
    assert report["metrics"]["e2e_tests"] == 5
    assert report["metrics"]["total_tests"] == 15
    assert report["quality_gates"]["unit_tests"]["status"] == "pass"
    assert report["quality_gates"]["e2e_tests"]["status"] == "pass"


async def test_generate_demo_report_some_fail():
    state = {
        "test_counts": {"passed": 8, "failed": 2, "errors": 0, "total": 10},
        "tests_passed": False,
        "e2e_counts": {"passed": 3, "failed": 1, "errors": 0, "total": 4},
        "e2e_passed": False,
        "issue_stats": {"open": 5, "closed_today": 1},
        "security_scan": {
            "semgrep_high": 1,
            "semgrep_status": "fail",
            "coverage_pct": 60.0,
            "coverage_status": "fail",
        },
    }
    result = await generate_demo_report(state)
    report = result["demo_report"]
    assert report["overall_status"] == "red"
    assert report["quality_gates"]["unit_tests"]["status"] == "fail"
    assert report["quality_gates"]["e2e_tests"]["status"] == "fail"


async def test_generate_demo_report_no_tests():
    state = {}
    result = await generate_demo_report(state)
    report = result["demo_report"]
    assert report["metrics"]["total_tests"] == 0
    assert report["overall_status"] == "red"


# ── write_e2e_tests (stub) ───────────────────────────────────────────


async def test_write_e2e_tests_stub():
    result = await write_e2e_tests({"claude": None, "workspace": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── run_unit_tests (stub) ─────────────────────────────────────────────


async def test_run_unit_tests_stub():
    result = await run_unit_tests({"claude": None, "workspace": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── run_e2e_tests (stub) ──────────────────────────────────────────────


async def test_run_e2e_tests_stub():
    result = await run_e2e_tests({"claude": None, "workspace": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── run_security_scan (stub) ──────────────────────────────────────────


async def test_run_security_scan_stub():
    result = await run_security_scan({"claude": None, "workspace": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── collect_issue_status ──────────────────────────────────────────────


async def test_collect_issue_status_no_github():
    result = await collect_issue_status({"github": None})
    assert result["tokens_used"] == 0
    assert result["issue_stats"]["open"] == 0
    assert result["issue_stats"]["closed_today"] == 0
