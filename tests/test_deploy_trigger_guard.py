"""A daily plan must never redeploy the service.

The PO agent writes docs/daily-plans/<date>.md directly to main. Because
every push to main deploys, that commit replaced the container and wiped the
in-memory cycle tracker: a cycle running against theswarm itself died as
soon as its own PO phase committed the plan it had just written
(prod cycle e80598e4bc4a, 2026-09-07 — PO ok, killed 40s into TechLead).
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
# PyYAML parses the bare key `on:` as the boolean True.
TRIGGERS = CI.get("on") or CI.get(True)


def test_daily_plans_do_not_trigger_the_pipeline():
    assert "docs/daily-plans/**" in TRIGGERS["push"]["paths-ignore"]


def test_pushes_to_main_still_deploy_everything_else():
    """The guard must be a path filter, not a disabled trigger."""
    assert TRIGGERS["push"]["branches"] == ["main"]
    ignored = TRIGGERS["push"]["paths-ignore"]
    assert "src/**" not in ignored and "**" not in ignored


def test_pull_requests_are_never_path_filtered():
    """Every PR runs the full suite, whatever it touches."""
    assert "paths-ignore" not in TRIGGERS["pull_request"]


def test_the_po_still_writes_the_plan_where_the_filter_expects_it():
    """If the PO's path moves, the filter silently stops working."""
    po = Path("src/theswarm/agents/po.py").read_text()
    assert 'f"docs/daily-plans/{today}.md"' in po
