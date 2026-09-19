"""Unit tests for the harness's structured-result trail (M5, issue #79)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cycle_e2e.py"
_spec = importlib.util.spec_from_file_location("cycle_e2e", SCRIPT_PATH)
cycle_e2e = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("cycle_e2e", cycle_e2e)
_spec.loader.exec_module(cycle_e2e)

build_result = cycle_e2e.build_result
append_result = cycle_e2e.append_result


def test_build_result_passes_when_cycle_completed_with_prs_and_no_unfinished_children():
    prs = [{"number": 42, "state": "open", "ci": "green"}]

    result = build_result(
        repo="jrechet/concert-tour-app",
        feature="Show the remaining ticket count on each concert card\n\nmore detail",
        cycle_id="cycle-123",
        state="completed",
        last_phase="qa",
        prs=prs,
        left=[],
        timestamp="2026-09-19T12:00:00+00:00",
    )

    assert result == {
        "timestamp": "2026-09-19T12:00:00+00:00",
        "repo": "jrechet/concert-tour-app",
        "feature": "Show the remaining ticket count on each concert card",
        "cycle_id": "cycle-123",
        "state": "completed",
        "last_phase": "qa",
        "prs": prs,
        "unfinished": [],
        "passed": True,
        "reasons": [],
    }


def test_build_result_lists_all_reasons_when_cycle_failed_no_prs_and_children_left():
    result = build_result(
        repo="jrechet/concert-tour-app",
        feature="Add refund flow",
        cycle_id="cycle-456",
        state="timeout",
        last_phase="dev",
        prs=[],
        left=[101, 102, 103],
        timestamp="2026-09-19T13:30:00+00:00",
    )

    assert result["passed"] is False
    assert result["unfinished"] == [101, 102, 103]
    assert result["reasons"] == [
        "cycle timeout",
        "no pull request produced",
        "3 sub-task(s) left unbuilt",
    ]


def test_append_result_appends_one_json_line_without_touching_existing_lines(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    first = {"cycle_id": "one", "passed": True}
    second = {"cycle_id": "two", "passed": False}

    append_result(history, first)
    append_result(history, second)

    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == first
    assert json.loads(lines[1]) == second


def test_append_result_creates_parent_directories_when_history_file_does_not_exist_yet(tmp_path):
    history = tmp_path / "nested" / "dir" / "harness-runs.jsonl"
    result = {"cycle_id": "abc", "passed": True}

    assert not history.parent.exists()
    append_result(history, result)

    assert history.exists()
    assert json.loads(history.read_text(encoding="utf-8").strip()) == result
