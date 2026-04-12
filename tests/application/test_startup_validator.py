"""Tests for StartupValidator."""

from __future__ import annotations

import os

import pytest

from theswarm.application.services.startup_validator import StartupValidator


@pytest.fixture
def validator():
    return StartupValidator()


class TestValidate:
    def test_all_set(self, validator, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp-test")
        monkeypatch.setenv("SWARM_GITHUB_REPO", "owner/repo")
        monkeypatch.setenv("EXTERNAL_URL", "https://swarm.example.com")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm-test")
        result = validator.validate()
        assert result.ok
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

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
