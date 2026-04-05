"""Tests for multi-repo support in TheSwarm."""

import pytest

from theswarm.persona import _extract_repo


ALLOWED = ["jrechet/swarm-todo-app", "jrechet/espace-client"]
DEFAULT = "jrechet/swarm-todo-app"


class TestExtractRepo:

    def test_explicit_on_syntax(self):
        assert _extract_repo("go on jrechet/espace-client", ALLOWED, DEFAULT) == "jrechet/espace-client"

    def test_explicit_sur_syntax(self):
        assert _extract_repo("lance le cycle sur jrechet/espace-client", ALLOWED, DEFAULT) == "jrechet/espace-client"

    def test_repo_colon_syntax(self):
        assert _extract_repo("repo: jrechet/espace-client go", ALLOWED, DEFAULT) == "jrechet/espace-client"

    def test_falls_back_to_default(self):
        assert _extract_repo("go", ALLOWED, DEFAULT) == DEFAULT

    def test_unknown_repo_falls_back(self):
        assert _extract_repo("go on unknown/repo", ALLOWED, DEFAULT) == DEFAULT

    def test_empty_message(self):
        assert _extract_repo("", ALLOWED, DEFAULT) == DEFAULT

    def test_no_allowed_repos(self):
        assert _extract_repo("go on jrechet/espace-client", [], "") == ""

    def test_case_sensitivity(self):
        """Repo names are case-sensitive (GitHub convention)."""
        assert _extract_repo("go on jrechet/espace-client", ALLOWED, DEFAULT) == "jrechet/espace-client"
