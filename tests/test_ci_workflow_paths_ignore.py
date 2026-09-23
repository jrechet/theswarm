"""The scheduled e2e harness must not redeploy the service either.

Same trap as docs/daily-plans/** (see test_deploy_trigger_guard.py) and
docs/cycle-history.jsonl: .github/workflows/harness.yml commits its result
straight to docs/harness-runs.jsonl on main. Without a paths-ignore entry
that push would trigger CI and a deploy, killing whatever the harness itself
just kicked off — this guards the entry against silently drifting away, the
way static/v2/app.css's .gitignore pattern once did.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
# PyYAML parses the bare key `on:` as the boolean True.
CI_TRIGGERS = CI.get("on") or CI.get(True)

HARNESS = yaml.safe_load(Path(".github/workflows/harness.yml").read_text())
HARNESS_TRIGGERS = HARNESS.get("on") or HARNESS.get(True)


def test_harness_history_path_is_excluded_from_ci_trigger():
    assert "docs/harness-runs.jsonl" in CI_TRIGGERS["push"]["paths-ignore"]


def test_harness_workflow_is_valid_yaml_with_schedule_and_dispatch_triggers():
    assert "schedule" in HARNESS_TRIGGERS
    assert "workflow_dispatch" in HARNESS_TRIGGERS


def test_harness_workflow_schedule_has_a_cron_entry():
    schedule = HARNESS_TRIGGERS["schedule"]
    assert schedule
    assert all("cron" in entry for entry in schedule)


def test_harness_workflow_default_repo_is_the_regression_probe_not_theswarm():
    """jrechet/theswarm is a manual workflow_dispatch override only — an
    unattended run against the swarm's own repo would queue behind or block
    on the one-cycle-per-repo lock and the held-PR merge step (AGENTS.md)."""
    repo_input = HARNESS_TRIGGERS["workflow_dispatch"]["inputs"]["repo"]
    assert repo_input["default"] == "jrechet/concert-tour-app"
    assert repo_input["default"] != "jrechet/theswarm"


def test_harness_workflow_dispatch_also_accepts_a_feature_input():
    """A typed feature still runs as before; an empty one (the default since
    V2 M6) means the eval manifest's feature of the day, and `all` runs the
    whole series — the scheduled run takes the rotation."""
    inputs = HARNESS_TRIGGERS["workflow_dispatch"]["inputs"]
    assert "feature" in inputs
    assert inputs["feature"]["default"] == ""
    assert inputs["all"]["type"] == "boolean"
    assert inputs["all"]["default"] is False
