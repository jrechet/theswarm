"""Tests for StartupValidator."""

from __future__ import annotations

import os

import pytest

from theswarm.application.services.startup_validator import StartupValidator


@pytest.fixture
def validator():
    return StartupValidator()


class TestValidate:
    def test_all_set(self, validator, monkeypatch, tmp_path):
        from theswarm.application.services import startup_validator as sv

        (tmp_path / "app.css").write_text("/* built */")  # the generated stylesheet, built
        monkeypatch.setattr(sv, "STYLESHEET", tmp_path / "app.css")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        monkeypatch.setenv("SWARM_GITHUB_REPO", "owner/repo")
        monkeypatch.setenv("EXTERNAL_URL", "https://swarm.example.com")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-test")
        monkeypatch.setenv("SWARM_VAULT_MASTER_KEY", "fake-fernet-key")
        # A fully-configured deployment runs with the auth wall up (issue #38)
        monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
        monkeypatch.setenv("SWARM_ACCESS_KEY", "fake-access-key")
        monkeypatch.setenv("SWARM_SESSION_SECRET", "fake-session-secret")
        result = validator.validate()
        assert result.ok
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_missing_vault_master_key_warns(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-test")
        monkeypatch.delenv("SWARM_VAULT_MASTER_KEY", raising=False)
        result = validator.validate()
        assert result.ok
        assert any("SWARM_VAULT_MASTER_KEY" in w for w in result.warnings)

    def test_missing_anthropic_key(self, validator, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = validator.validate()
        assert not result.ok
        assert any("ANTHROPIC_API_KEY" in e for e in result.errors)

    def test_missing_github_token_warns(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        result = validator.validate()
        assert any("GITHUB_TOKEN" in w for w in result.warnings)

    def test_invalid_repo_format(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("SWARM_GITHUB_REPO", "just-a-name")
        result = validator.validate()
        assert not result.ok
        assert any("owner/repo" in e for e in result.errors)

    def test_valid_repo_format(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("SWARM_GITHUB_REPO", "owner/repo")
        result = validator.validate()
        assert not any("SWARM_GITHUB_REPO" in e for e in result.errors)

    def test_bad_external_url_warns(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("EXTERNAL_URL", "not-a-url")
        result = validator.validate()
        assert any("EXTERNAL_URL" in w for w in result.warnings)

    def test_no_mattermost_token_warns(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("SWARM_PO_MATTERMOST_TOKEN", raising=False)
        monkeypatch.delenv("MATTERMOST_BOT_TOKEN", raising=False)
        result = validator.validate()
        assert any("Mattermost" in w for w in result.warnings)

    def test_skip_api_key_check(self, validator, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = validator.validate(require_api_keys=False)
        assert result.ok

    def test_empty_repo_no_error(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("SWARM_GITHUB_REPO", raising=False)
        result = validator.validate()
        assert not any("SWARM_GITHUB_REPO" in e for e in result.errors)


class TestValidateAndLog:
    def test_logs_warnings(self, validator, monkeypatch, caplog):
        import logging
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with caplog.at_level(logging.WARNING):
            validator.validate_and_log()
        assert "GITHUB_TOKEN" in caplog.text

    def test_logs_errors(self, validator, monkeypatch, caplog):
        import logging
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with caplog.at_level(logging.ERROR):
            validator.validate_and_log()
        assert "ANTHROPIC_API_KEY" in caplog.text


class TestSubscriptionNeedsNoApiKey:
    """The Agent SDK runs on the subscription (V2 invariant I1): an API key is
    the fallback, and its absence is the normal state. `python -m theswarm
    validate` answered `identity=subscription` and then exited 1 on
    "ANTHROPIC_API_KEY not set" (2026-10-05) — the Quickstart's first step."""

    def test_no_api_key_is_fine_on_the_sdk(self, validator, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = validator.validate()
        assert result.ok and not any("ANTHROPIC_API_KEY" in e for e in result.errors)

    def test_no_api_key_is_fine_in_auto_mode(self, validator, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "auto")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert validator.validate().ok

    def test_the_api_backend_still_needs_its_key(self, validator, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "api")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = validator.validate()
        assert not result.ok and any("SWARM_CLAUDE_BACKEND=api" in e for e in result.errors)


class TestTheStylesheetIsBuilt:
    """`static/v3/app.css` is generated (never committed): on a fresh clone the
    Quickstart's first page rendered in Times with blue links (2026-10-05)."""

    def test_a_missing_stylesheet_is_a_warning_naming_the_command(self, validator, monkeypatch, tmp_path):
        from theswarm.application.services import startup_validator as sv

        monkeypatch.setattr(sv, "STYLESHEET", tmp_path / "app.css")
        result = validator.validate(require_api_keys=False)
        assert result.ok
        assert any("app.css" in w and "scripts/build-css.sh" in w for w in result.warnings)

    def test_a_built_stylesheet_warns_nothing(self, validator, monkeypatch, tmp_path):
        from theswarm.application.services import startup_validator as sv

        (tmp_path / "app.css").write_text("/* built */")
        monkeypatch.setattr(sv, "STYLESHEET", tmp_path / "app.css")
        assert not any("app.css" in w for w in validator.validate(require_api_keys=False).warnings)
