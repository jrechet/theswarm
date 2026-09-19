"""Unit tests for the standalone cycle_e2e.py harness script.

The script lives in scripts/ (not a package), so it's loaded by file path
rather than imported normally.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "cycle_e2e", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cycle_e2e.py"
)
cycle_e2e = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cycle_e2e)


def test_is_regression_true_when_previous_passed_and_current_failed():
    previous = {"repo": "acme/app", "passed": True}
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(previous, current) is True


def test_is_regression_false_when_previous_is_none():
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(None, current) is False


def test_is_regression_false_when_previous_already_failed():
    previous = {"repo": "acme/app", "passed": False}
    current = {"repo": "acme/app", "passed": False}

    assert cycle_e2e.is_regression(previous, current) is False


def test_read_last_result_returns_most_recent_entry_for_matching_repo_only(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    entries = [
        {"repo": "acme/app", "passed": True, "seq": 1},
        {"repo": "other/app", "passed": True, "seq": 2},
        {"repo": "acme/app", "passed": False, "seq": 3},
        {"repo": "other/app", "passed": False, "seq": 4},
    ]
    history.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    result = cycle_e2e.read_last_result(history, "acme/app")

    assert result == {"repo": "acme/app", "passed": False, "seq": 3}


def test_read_last_result_returns_none_when_history_file_is_absent(tmp_path):
    history = tmp_path / "does-not-exist.jsonl"

    assert cycle_e2e.read_last_result(history, "acme/app") is None


def test_read_last_result_ignores_unparseable_lines(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    history.write_text(
        "not json\n" + json.dumps({"repo": "acme/app", "passed": True}) + "\n"
    )

    result = cycle_e2e.read_last_result(history, "acme/app")

    assert result == {"repo": "acme/app", "passed": True}


def test_read_last_result_returns_none_when_no_lines_match_repo(tmp_path):
    history = tmp_path / "harness-runs.jsonl"
    history.write_text(json.dumps({"repo": "other/app", "passed": True}) + "\n")

    assert cycle_e2e.read_last_result(history, "acme/app") is None
