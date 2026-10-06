"""QA's security gate runs bandit beside semgrep (owner, 2026-10-06).

semgrep's OWASP rules run through `uv tool run` since 2026-09-25; bandit adds
the Python-specific checks (shell=True, hard-coded passwords, pickle, yaml.load,
weak hashes). A HIGH finding from either fails the gate; the gate's detail
says what each found.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from theswarm.agents import qa
from theswarm.agents.qa import run_security_scan
from theswarm.application.services.report_generator import _qa_gate_detail
from theswarm.domain.reporting.value_objects import QualityStatus

SEMGREP_CLEAN = json.dumps({"results": []})


def _bandit(*severities: str) -> str:
    return json.dumps({"results": [{"issue_severity": s, "issue_confidence": "HIGH", "test_id": "B602",
                                    "filename": "src/app.py", "line_number": 7} for s in severities],
                       "metrics": {"_totals": {"loc": 120}}})


def _state(tmp_path, outputs: list[tuple[str, bool]]) -> dict:
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[{"output": o, "passed": p} for o, p in outputs])
    return {"claude": claude, "workspace": str(tmp_path),
            "security_scan": {"coverage_pct": 90.0, "coverage_status": "pass", "coverage_reason": ""}}


def test_the_command_is_pinned_and_can_be_turned_off(monkeypatch):
    monkeypatch.delenv("SWARM_QA_BANDIT", raising=False)
    monkeypatch.setattr(qa.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)

    command = qa._bandit_command()

    assert command[:4] == ["/usr/bin/uv", "tool", "run", "--from"] and command[4] == f"bandit=={qa.BANDIT_VERSION}"
    assert "-f" in command and "json" in command and "-r" in command and "src/" in command

    monkeypatch.setenv("SWARM_QA_BANDIT", "0")
    assert qa._bandit_command() is None


async def test_a_high_finding_fails_the_scan(tmp_path):
    state = _state(tmp_path, [(SEMGREP_CLEAN, True), (_bandit("HIGH", "LOW"), False)])

    scan = (await run_security_scan(state))["security_scan"]

    assert scan["semgrep_status"] == "pass" and scan["semgrep_high"] == 0
    assert scan["bandit_status"] == "fail" and scan["bandit_high"] == 1
    assert scan["coverage_pct"] == 90.0  # carried forward untouched


async def test_medium_and_low_findings_pass(tmp_path):
    state = _state(tmp_path, [(SEMGREP_CLEAN, True), (_bandit("MEDIUM", "LOW"), False)])

    scan = (await run_security_scan(state))["security_scan"]

    assert scan["bandit_status"] == "pass" and scan["bandit_high"] == 0 and scan["bandit_findings"] == 2


async def test_a_bandit_that_cannot_run_is_not_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_QA_BANDIT", "0")
    state = _state(tmp_path, [(SEMGREP_CLEAN, True)])

    scan = (await run_security_scan(state))["security_scan"]

    assert scan["bandit_status"] == "not_run" and scan["bandit_high"] == 0
    assert state["claude"].run_tests.await_count == 1  # semgrep only


async def test_the_gate_reads_both(tmp_path):
    """The demo report's security gate: one HIGH anywhere is red; the detail
    names both scanners."""
    from theswarm.agents.qa import generate_demo_report

    async def gate_for(security: dict) -> dict:
        report = await generate_demo_report({
            "workspace": str(tmp_path), "unit_tests_passed": True,
            "unit_tests_output": "3 passed in 0.1s", "e2e_passed": True, "e2e_output": "2 passed",
            "e2e_counts": {"passed": 2, "failed": 0, "errors": 0, "total": 2},
            "security_scan": {**security, "coverage_pct": 90.0, "coverage_status": "pass"},
            "screenshots": [], "video_path": None, "feature_calls": {"routes": [], "calls": []},
        })
        return report["demo_report"]["quality_gates"]["security"]

    red = await gate_for({"semgrep_high": 0, "semgrep_status": "pass", "bandit_high": 2, "bandit_status": "fail"})
    assert red["status"] == "fail" and red["bandit_high"] == 2
    green = await gate_for({"semgrep_high": 0, "semgrep_status": "pass", "bandit_high": 0, "bandit_status": "pass"})
    assert green["status"] == "pass"
    half = await gate_for({"semgrep_high": 0, "semgrep_status": "not_run", "bandit_high": 0, "bandit_status": "pass"})
    assert half["status"] == "pass"
    none = await gate_for({"semgrep_high": 0, "semgrep_status": "not_run", "bandit_high": 0, "bandit_status": "not_run"})
    assert none["status"] == "not_run"


@pytest.mark.parametrize("gate,expected", [
    ({"semgrep_high": 0, "semgrep_status": "pass", "bandit_high": 1, "bandit_status": "fail", "status": "fail"},
     "semgrep 0 HIGH · bandit 1 HIGH"),
    ({"semgrep_high": 0, "status": "pass"}, "0 HIGH findings"),
])
def test_the_report_detail_names_both_scanners(gate, expected):
    assert _qa_gate_detail("security", gate, QualityStatus.PASS if gate["status"] == "pass" else QualityStatus.FAIL) == expected


# ── The first run of a scanner prints uv's install lines first (2026-10-06) ──
# `run_tests` merges stderr into stdout: on the cycle that introduced bandit
# (2e713964f7a3) its JSON came after "Installed 7 packages in 312ms" and QA
# read "bandit printed no JSON (exit 0)".

INSTALL_LINES = "Resolved 7 packages in 1.2s\nInstalled 7 packages in 312ms\n + bandit==1.9.4\n + rich==14.0.0\n"


async def test_uv_s_install_lines_before_the_json_are_stepped_over(tmp_path):
    state = _state(tmp_path, [(INSTALL_LINES + SEMGREP_CLEAN, True), (INSTALL_LINES + _bandit("HIGH"), False)])

    scan = (await run_security_scan(state))["security_scan"]

    assert scan["semgrep_status"] == "pass"
    assert scan["bandit_status"] == "fail" and scan["bandit_high"] == 1


def test_the_json_is_found_after_the_noise():
    assert qa._json_from(INSTALL_LINES + '{"results": []}') == {"results": []}
    assert qa._json_from('{"a": 1}\n') == {"a": 1}
    with pytest.raises(ValueError):
        qa._json_from("no json here")
