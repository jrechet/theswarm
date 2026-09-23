"""CI runs on every pull request, whatever its base branch.

The V2 runtime lands as stacked PRs (M0 ← M1 ← M2 …), each against the
previous milestone's branch. `pull_request: branches: [main]` gave those
no checks at all — "no checks reported" — and a PR without CI cannot be
merged with confidence. The deploy stays a `push` to main.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CI = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
TRIGGERS = CI.get("on") or CI.get(True)


def test_pull_requests_trigger_ci_on_any_base():
    assert "pull_request" in TRIGGERS
    assert not (TRIGGERS["pull_request"] or {}).get("branches")


def test_the_deploy_trigger_is_still_a_push_to_main_only():
    assert TRIGGERS["push"]["branches"] == ["main"]
