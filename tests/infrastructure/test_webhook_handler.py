"""Tests for WebhookHandler."""

from __future__ import annotations

import pytest

from theswarm.infrastructure.scheduling.webhook_handler import (
    WebhookEvent,
    WebhookHandler,
)


@pytest.fixture
def handler():
    return WebhookHandler(webhook_secret="test-secret")


@pytest.fixture
def handler_no_secret():
    return WebhookHandler()


class TestVerifySignature:
    def test_valid_signature(self, handler):
        import hashlib
        import hmac

        payload = b'{"action": "opened"}'
        sig = "sha256=" + hmac.new(
            b"test-secret", payload, hashlib.sha256
        ).hexdigest()
        assert handler.verify_signature(payload, sig)

    def test_invalid_signature(self, handler):
        assert not handler.verify_signature(b"payload", "sha256=bad")

    def test_missing_prefix(self, handler):
        assert not handler.verify_signature(b"payload", "md5=something")

    def test_no_secret_always_valid(self, handler_no_secret):
        assert handler_no_secret.verify_signature(b"anything", "sha256=whatever")


class TestParseEvent:
    def test_push_event(self, handler):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "alice"},
        }
        event = handler.parse_event("push", payload)
        assert event.event_type == "push"
        assert event.ref == "refs/heads/main"
        assert event.repo_full_name == "owner/repo"
        assert event.sender == "alice"

    def test_pr_event(self, handler):
        payload = {
            "action": "opened",
            "pull_request": {"head": {"ref": "feat/new"}},
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "bob"},
        }
        event = handler.parse_event("pull_request", payload)
        assert event.event_type == "pull_request"
        assert event.action == "opened"
        assert event.ref == "feat/new"

    def test_issue_event(self, handler):
        payload = {
            "action": "opened",
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "carol"},
        }
        event = handler.parse_event("issues", payload)
        assert event.event_type == "issues"
        assert event.action == "opened"

    def test_missing_fields(self, handler):
        event = handler.parse_event("push", {})
        assert event.repo_full_name == ""
        assert event.sender == ""


class TestShouldTriggerCycle:
    def test_push_to_main(self, handler):
        event = WebhookEvent("push", "", "owner/repo", "refs/heads/main", "alice")
        assert handler.should_trigger_cycle(event, ["owner/repo"])

    def test_push_to_feature_branch(self, handler):
        event = WebhookEvent("push", "", "owner/repo", "refs/heads/feat/x", "alice")
        assert not handler.should_trigger_cycle(event, ["owner/repo"])

    def test_push_to_non_allowed_repo(self, handler):
        event = WebhookEvent("push", "", "other/repo", "refs/heads/main", "alice")
        assert not handler.should_trigger_cycle(event, ["owner/repo"])

    def test_issue_opened(self, handler):
        event = WebhookEvent("issues", "opened", "owner/repo", "", "bob")
        assert handler.should_trigger_cycle(event, ["owner/repo"])

    def test_issue_closed(self, handler):
        event = WebhookEvent("issues", "closed", "owner/repo", "", "bob")
        assert not handler.should_trigger_cycle(event, ["owner/repo"])

    def test_pr_review_requested(self, handler):
        event = WebhookEvent("pull_request", "review_requested", "owner/repo", "feat/x", "carol")
        assert handler.should_trigger_cycle(event, ["owner/repo"])

    def test_pr_opened_no_trigger(self, handler):
        event = WebhookEvent("pull_request", "opened", "owner/repo", "feat/x", "carol")
        assert not handler.should_trigger_cycle(event, ["owner/repo"])

    def test_custom_default_branch(self, handler):
        event = WebhookEvent("push", "", "owner/repo", "refs/heads/develop", "alice")
        assert handler.should_trigger_cycle(event, ["owner/repo"], default_branch="develop")

    def test_unknown_event_type(self, handler):
        event = WebhookEvent("star", "created", "owner/repo", "", "fan")
        assert not handler.should_trigger_cycle(event, ["owner/repo"])
