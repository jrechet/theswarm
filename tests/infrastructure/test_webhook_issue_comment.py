"""Sprint F P1 — WebhookHandler extensions for /swarm implement trigger."""

from __future__ import annotations

import pytest

from theswarm.infrastructure.scheduling.webhook_handler import (
    WebhookEvent,
    WebhookHandler,
)


@pytest.fixture
def handler():
    return WebhookHandler()


class TestParseIssueComment:
    def test_extracts_comment_body_issue_number_and_sender(self, handler):
        payload = {
            "action": "created",
            "comment": {"body": "/swarm implement please", "user": {"login": "alice"}},
            "issue": {"number": 42, "html_url": "https://github.com/o/r/issues/42"},
            "repository": {"full_name": "o/r"},
            "sender": {"login": "alice"},
        }
        event = handler.parse_event("issue_comment", payload)
        assert event.event_type == "issue_comment"
        assert event.action == "created"
        assert event.repo_full_name == "o/r"
        assert event.sender == "alice"
        assert event.comment_body == "/swarm implement please"
        assert event.issue_number == 42

    def test_missing_comment_fields(self, handler):
        event = handler.parse_event("issue_comment", {})
        assert event.event_type == "issue_comment"
        assert event.comment_body == ""
        assert event.issue_number is None


class TestSlashCommandDetection:
    def test_exact_command(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="/swarm implement", issue_number=1,
        )
        assert handler.is_implement_command(event)

    def test_command_with_trailing_text(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="/swarm implement please make it fast", issue_number=1,
        )
        assert handler.is_implement_command(event)

    def test_command_with_leading_whitespace(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="  /swarm implement\n", issue_number=1,
        )
        assert handler.is_implement_command(event)

    def test_non_command_comment(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="LGTM", issue_number=1,
        )
        assert not handler.is_implement_command(event)

    def test_unrelated_slash_command(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="/swarm review", issue_number=1,
        )
        assert not handler.is_implement_command(event)

    def test_non_issue_comment_event(self, handler):
        event = WebhookEvent(
            event_type="push", action="", repo_full_name="o/r",
            ref="refs/heads/main", sender="alice",
            comment_body="/swarm implement", issue_number=None,
        )
        assert not handler.is_implement_command(event)


class TestAuthorization:
    def test_allowed_commenter(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="/swarm implement", issue_number=1,
        )
        assert handler.is_authorised(event, allowed_commenters=["alice", "bob"])

    def test_unknown_commenter_denied(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="eve",
            comment_body="/swarm implement", issue_number=1,
        )
        assert not handler.is_authorised(event, allowed_commenters=["alice", "bob"])

    def test_empty_allowlist_denies_all(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="alice",
            comment_body="/swarm implement", issue_number=1,
        )
        assert not handler.is_authorised(event, allowed_commenters=[])

    def test_wildcard_allowlist_permits_any(self, handler):
        event = WebhookEvent(
            event_type="issue_comment", action="created",
            repo_full_name="o/r", ref="", sender="new-contributor",
            comment_body="/swarm implement", issue_number=1,
        )
        assert handler.is_authorised(event, allowed_commenters=["*"])
