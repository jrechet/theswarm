"""0% coverage under a suite that passed is a broken gauge, not a verdict.

Cycle 6 on this repository reported `coverage 0.0%` and filed it as a
**fail**, next to 2921 passing unit tests. `coverage.json` was there and
said so honestly: `percent_covered: 0.0`. Coverage had run and instrumented
nothing — the same run on cycle 5 measured 87%.

A gauge that reads zero while the engine runs is not reporting a low
figure, it is reporting that it is not connected. Filing it as `fail` sends
the reader hunting for untested code that does not exist; the swarm's own
PO said as much in its report: *"more likely a broken coverage pipeline
than an accurate signal"*.

`num_statements` is what tells the two apart: zero statements instrumented
means no file under `--cov=src` was measured at all.
"""

from __future__ import annotations

import json

from theswarm.agents.qa import _read_coverage


def _write(tmp_path, totals: dict) -> str:
    (tmp_path / "coverage.json").write_text(json.dumps({"totals": totals}))
    return str(tmp_path)


def test_a_real_figure_is_reported_as_measured(tmp_path):
    workspace = _write(tmp_path, {"percent_covered": 87.0, "num_statements": 12000})

    pct, status, reason = _read_coverage(workspace)

    assert (pct, status) == (87.0, "pass")
    assert reason == ""


def test_a_low_but_real_figure_still_fails(tmp_path):
    workspace = _write(tmp_path, {"percent_covered": 41.0, "num_statements": 12000})

    pct, status, _ = _read_coverage(workspace)

    assert (pct, status) == (41.0, "fail")


def test_zero_statements_is_not_run_not_a_failure(tmp_path):
    """The cycle 6 shape: the file is there, and it measured nothing."""
    workspace = _write(tmp_path, {"percent_covered": 0.0, "num_statements": 0})

    pct, status, reason = _read_coverage(workspace)

    assert status == "not_run", (
        "0% over 0 statements is an unplugged gauge; calling it a failure "
        "sends the reader after untested code that does not exist"
    )
    assert "instrumented no files" in reason
    assert pct == 0.0


def test_a_missing_file_is_still_not_run(tmp_path):
    pct, status, reason = _read_coverage(str(tmp_path))

    assert (pct, status) == (0.0, "not_run")
    assert reason == "coverage.json not found"


def test_unreadable_json_does_not_crash_the_phase(tmp_path):
    (tmp_path / "coverage.json").write_text("{not json")

    pct, status, reason = _read_coverage(str(tmp_path))

    assert (pct, status) == (0.0, "not_run")
    assert reason


def test_a_report_without_a_statement_count_is_trusted(tmp_path):
    """Absent is not zero — older reports simply do not carry the field."""
    workspace = _write(tmp_path, {"percent_covered": 85.0})

    pct, status, reason = _read_coverage(workspace)

    assert (pct, status, reason) == (85.0, "pass", "")
