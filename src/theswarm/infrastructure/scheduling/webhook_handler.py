"""GitHub webhook handler that can trigger cycles on push/PR events."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


_IMPLEMENT_COMMAND = "/swarm implement"

# V2 runtime M8 — the GitHub-native doors. A label on an issue starts a
# targeted cycle the way ▶ Play does; `@swarm <instruction>` from the owner
# on a pull request sends the instruction to the Dev as a review would.
DEFAULT_GO_LABEL = "swarm:go"
_INSTRUCTION_MENTION = "@swarm"


def go_label() -> str:
    return os.environ.get("SWARM_GO_LABEL", "").strip() or DEFAULT_GO_LABEL


@dataclass(frozen=True)
class WebhookEvent:
    """Parsed GitHub webhook event."""

    event_type: str  # "push", "pull_request", "issues", "issue_comment"
    action: str  # "opened", "closed", "synchronize", "created", etc.
    repo_full_name: str  # "owner/repo"
    ref: str  # "refs/heads/main"
    sender: str  # GitHub username
    # Sprint F P1 — issue_comment fields
    comment_body: str = ""
    issue_number: int | None = None
    # V2 M8 — labels and pull-request comments
    label: str = ""
    issue_is_pr: bool = False
    issue_title: str = ""
    issue_body: str = ""


class WebhookHandler:
    """Processes incoming GitHub webhook events.

    Validates signatures, parses events, and decides whether to trigger
    a development cycle based on the event type and configured rules.
    """

    def __init__(self, webhook_secret: str = "") -> None:
        self._secret = webhook_secret

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the X-Hub-Signature-256 header."""
        if not self._secret:
            return True  # No secret configured, skip verification
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(
            self._secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    def parse_event(self, event_type: str, payload: dict) -> WebhookEvent:
        """Parse a GitHub webhook payload into a WebhookEvent."""
        repo = payload.get("repository", {})
        sender = payload.get("sender", {})

        action = payload.get("action", "")
        ref = payload.get("ref", "")
        comment_body = ""
        issue_number: int | None = None
        label = ""
        issue_is_pr = False
        issue_title = ""
        issue_body = ""

        if event_type == "pull_request":
            pr = payload.get("pull_request", {})
            ref = pr.get("head", {}).get("ref", "")
        elif event_type in ("issue_comment", "issues"):
            issue = payload.get("issue", {}) or {}
            raw_num = issue.get("number")
            if isinstance(raw_num, int):
                issue_number = raw_num
            issue_is_pr = bool(issue.get("pull_request"))
            issue_title = str(issue.get("title") or "")
            issue_body = str(issue.get("body") or "")
            if event_type == "issue_comment":
                comment = payload.get("comment", {}) or {}
                comment_body = comment.get("body", "") or ""
            else:
                label = str((payload.get("label") or {}).get("name") or "")

        return WebhookEvent(
            event_type=event_type,
            action=action,
            repo_full_name=repo.get("full_name", ""),
            ref=ref,
            sender=sender.get("login", ""),
            comment_body=comment_body,
            issue_number=issue_number,
            label=label,
            issue_is_pr=issue_is_pr,
            issue_title=issue_title,
            issue_body=issue_body,
        )

    # V2 M8 — the GitHub-native doors

    @staticmethod
    def is_go_label(event: WebhookEvent, label: str | None = None) -> bool:
        """`swarm:go` (SWARM_GO_LABEL) put on an issue: build it."""
        return (
            event.event_type == "issues"
            and event.action == "labeled"
            and bool(event.issue_number)
            and not event.issue_is_pr
            and event.label == (label or go_label())
        )

    @staticmethod
    def swarm_instruction(event: WebhookEvent) -> str | None:
        """The text after `@swarm` in a new comment on a pull request, or None."""
        if event.event_type != "issue_comment" or event.action != "created":
            return None
        if not event.issue_is_pr or not event.issue_number:
            return None
        body = event.comment_body.strip()
        if not body.lower().startswith(_INSTRUCTION_MENTION):
            return None
        rest = body[len(_INSTRUCTION_MENTION):]
        if rest and not rest[0].isspace() and rest[0] not in ",:":
            return None  # "@swarmbot" is somebody else
        return rest.lstrip(" ,:\t").strip()

    @staticmethod
    def is_owner(event: WebhookEvent, owner_login: str) -> bool:
        return bool(owner_login) and event.sender.lower() == owner_login.lower()

    def should_trigger_cycle(
        self,
        event: WebhookEvent,
        allowed_repos: list[str],
        default_branch: str = "main",
    ) -> bool:
        """Decide if this event should trigger a dev cycle."""
        if event.repo_full_name not in allowed_repos:
            log.debug("Ignoring event from non-allowed repo: %s", event.repo_full_name)
            return False

        # Trigger on push to default branch
        if event.event_type == "push":
            return event.ref == f"refs/heads/{default_branch}"

        # Trigger on new issues
        if event.event_type == "issues" and event.action == "opened":
            return True

        # Trigger on PR review requested
        if event.event_type == "pull_request" and event.action == "review_requested":
            return True

        return False

    # Sprint F P1 — /swarm implement slash command

    def is_implement_command(self, event: WebhookEvent) -> bool:
        """Return True if the comment body starts with /swarm implement."""
        if event.event_type != "issue_comment":
            return False
        body = event.comment_body.strip().lower()
        if not body.startswith(_IMPLEMENT_COMMAND):
            return False
        # Either exact command, or followed by whitespace + extra text
        rest = body[len(_IMPLEMENT_COMMAND):]
        return rest == "" or rest[0].isspace()

    def is_authorised(
        self,
        event: WebhookEvent,
        allowed_commenters: list[str],
    ) -> bool:
        """Check that the commenter is in the allowlist.

        An allowlist containing ``"*"`` permits any user. An empty
        allowlist denies everyone (fail-closed default).
        """
        if "*" in allowed_commenters:
            return True
        return event.sender in allowed_commenters
