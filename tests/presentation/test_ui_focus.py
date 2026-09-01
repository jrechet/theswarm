"""The UI answers one job: build a feature and follow it transparently.

17 nav entries, 54 fragments and 16 accordions on the project page buried
that job. Secondary surfaces are demoted, not deleted — their routes still
work, they just stop competing with the main path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path("src/theswarm/presentation/web/templates")
BASE = (TEMPLATES / "base.html").read_text()
PROJECT = (TEMPLATES / "projects_detail.html").read_text()


def _primary_nav_links() -> list[str]:
    block = BASE.split('<ul class="nav-primary">')[1].split("</ul>")[0]
    return re.findall(r"<span>([^<]+)</span>", block)


def _advanced_nav_links() -> list[str]:
    block = BASE.split("<summary>Advanced</summary>")[1].split("</details>")[0]
    return re.findall(r"<span>([^<]+)</span>", block)


# ── Navigation ─────────────────────────────────────────────────────────


def test_primary_nav_is_the_job_and_nothing_else():
    assert _primary_nav_links() == ["Projects", "Cycles", "Demos"]


def test_secondary_surfaces_are_demoted_not_deleted():
    advanced = _advanced_nav_links()
    for surface in ("Architect", "Scout", "Memory", "Prompts", "Refactors",
                    "Chief of Staff", "Proposals", "Dashboard"):
        assert surface in advanced, f"{surface} should be reachable under Advanced"


def test_advanced_group_is_collapsed_by_default():
    advanced_open = BASE.split("<summary>Advanced</summary>")[0].rstrip().endswith(
        "<details>",
    )
    assert advanced_open, "Advanced must be a plain <details>, not <details open>"


# ── Landing page ───────────────────────────────────────────────────────


def test_root_belongs_to_the_v2_flow():
    """`/` is the V2 picker now (tests/presentation/test_v2_flow.py); the
    dashboard module must no longer claim it."""
    source = Path("src/theswarm/presentation/web/routes/dashboard.py").read_text()
    assert '@router.get("/"' not in source

    app_source = Path("src/theswarm/presentation/web/app.py").read_text()
    assert app_source.index("app.include_router(v2.router)") < \
        app_source.index("app.include_router(dashboard.router)")


def test_dashboard_stays_reachable_at_its_own_path():
    source = (Path("src/theswarm/presentation/web/routes/dashboard.py")).read_text()
    assert '@router.get("/dashboard", response_class=HTMLResponse)' in source


# ── Project page ───────────────────────────────────────────────────────


def test_the_job_comes_before_the_configuration():
    """Composer and issue board must precede the Advanced block."""
    composer = PROJECT.index("Describe the next sprint")
    board = PROJECT.index('data-testid="issues-board-slot"')
    advanced = PROJECT.index('data-testid="project-advanced"')

    assert composer < board < advanced


def test_configuration_and_roles_live_under_advanced():
    advanced_block = PROJECT.split('data-testid="project-advanced"')[1]
    for buried in ("<h2>Configuration</h2>", "<h2>Secrets</h2>",
                   'data-testid="role-groups"'):
        assert buried in advanced_block


def test_role_panels_are_still_present():
    """Demoted, not deleted — all fourteen role groups survive."""
    assert PROJECT.count('class="role-group" data-role=') == 14


@pytest.mark.parametrize("slot", [
    "issues-board-slot",      # pick what to build
    "sprint-composer",        # describe what to build
])
def test_core_surfaces_remain_outside_advanced(slot):
    before_advanced = PROJECT.split('data-testid="project-advanced"')[0]
    assert slot in before_advanced
