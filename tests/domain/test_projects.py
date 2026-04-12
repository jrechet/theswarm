"""Tests for domain/projects — 100% coverage target."""

from __future__ import annotations

import pytest

from theswarm.domain.projects.entities import Project, ProjectConfig
from theswarm.domain.projects.value_objects import (
    Framework,
    FrameworkInfo,
    RepoUrl,
    TicketSourceType,
)


# ── RepoUrl ─────────────────────────────────────────────────────


class TestRepoUrl:
    def test_valid_repo(self):
        r = RepoUrl("owner/repo")
        assert r.value == "owner/repo"
        assert r.owner == "owner"
        assert r.name == "repo"
        assert str(r) == "owner/repo"

    def test_https_clone_url(self):
        r = RepoUrl("jrechet/theswarm")
        assert r.https_clone_url == "https://github.com/jrechet/theswarm.git"

    def test_invalid_repo_no_slash(self):
        with pytest.raises(ValueError, match="Invalid repo format"):
            RepoUrl("noslash")

    def test_invalid_repo_empty(self):
        with pytest.raises(ValueError, match="Invalid repo format"):
            RepoUrl("")

    def test_invalid_repo_spaces(self):
        with pytest.raises(ValueError, match="Invalid repo format"):
            RepoUrl("owner/ repo")

    def test_repo_with_dots_and_hyphens(self):
        r = RepoUrl("my-org/my-repo.js")
        assert r.owner == "my-org"
        assert r.name == "my-repo.js"

    def test_frozen(self):
        r = RepoUrl("a/b")
        with pytest.raises(AttributeError):
            r.value = "c/d"  # type: ignore[misc]


# ── Framework ────────────────────────────────────────────────────


class TestFramework:
    def test_all_values(self):
        assert Framework.AUTO == "auto"
        assert Framework.FASTAPI == "fastapi"
        assert Framework.DJANGO == "django"
        assert Framework.FLASK == "flask"
        assert Framework.NEXTJS == "nextjs"
        assert Framework.EXPRESS == "express"
        assert Framework.GENERIC == "generic"


class TestTicketSourceType:
    def test_all_values(self):
        assert TicketSourceType.GITHUB == "github"
        assert TicketSourceType.JIRA == "jira"
        assert TicketSourceType.LINEAR == "linear"
        assert TicketSourceType.GITLAB == "gitlab"


class TestFrameworkInfo:
    def test_creation(self):
        fi = FrameworkInfo(
            framework=Framework.FASTAPI,
            test_command="pytest tests/",
            source_dir="src/",
            entry_point="src.main:app",
            default_branch="main",
        )
        assert fi.framework == Framework.FASTAPI
        assert fi.test_command == "pytest tests/"
        assert fi.source_dir == "src/"
        assert fi.entry_point == "src.main:app"
        assert fi.default_branch == "main"


# ── ProjectConfig ────────────────────────────────────────────────


class TestProjectConfig:
    def test_defaults(self):
        c = ProjectConfig()
        assert c.max_daily_stories == 3
        assert c.token_budget_po == 300_000
        assert c.token_budget_dev == 1_000_000

    def test_token_budgets_dict(self):
        c = ProjectConfig(token_budget_po=100, token_budget_dev=200)
        budgets = c.token_budgets
        assert budgets["po"] == 100
        assert budgets["dev"] == 200
        assert budgets["techlead"] == 600_000
        assert budgets["qa"] == 300_000


# ── Project ──────────────────────────────────────────────────────


class TestProject:
    def test_creation_defaults(self):
        p = Project(id="test", repo=RepoUrl("owner/repo"))
        assert p.id == "test"
        assert p.default_branch == "main"
        assert p.framework == Framework.AUTO
        assert p.ticket_source == TicketSourceType.GITHUB
        assert p.team_channel == ""
        assert p.schedule == ""
        assert p.config.max_daily_stories == 3

    def test_with_detected_framework(self):
        p = Project(id="test", repo=RepoUrl("owner/repo"))
        p2 = p.with_detected_framework(
            framework=Framework.DJANGO,
            test_command="python manage.py test",
            source_dir="myapp/",
            default_branch="develop",
        )
        assert p2.framework == Framework.DJANGO
        assert p2.test_command == "python manage.py test"
        assert p2.source_dir == "myapp/"
        assert p2.default_branch == "develop"
        # Preserved fields
        assert p2.id == "test"
        assert p2.repo == p.repo
        assert p2.ticket_source == p.ticket_source

    def test_with_detected_framework_empty_fallback(self):
        p = Project(
            id="test", repo=RepoUrl("owner/repo"),
            test_command="existing", source_dir="existing/", default_branch="main",
        )
        p2 = p.with_detected_framework(
            framework=Framework.GENERIC,
            test_command="",
            source_dir="",
            default_branch="",
        )
        assert p2.test_command == "existing"
        assert p2.source_dir == "existing/"
        assert p2.default_branch == "main"

    def test_frozen(self):
        p = Project(id="test", repo=RepoUrl("a/b"))
        with pytest.raises(AttributeError):
            p.id = "other"  # type: ignore[misc]
