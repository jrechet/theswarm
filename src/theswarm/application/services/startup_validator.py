"""Startup validation: check required config before running."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    """Result of startup validation."""

    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class StartupValidator:
    """Validates environment and configuration at startup.

    Fail-fast instead of discovering missing config mid-cycle.
    """

    def validate(self, require_api_keys: bool = True) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        if require_api_keys:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                errors.append(
                    "ANTHROPIC_API_KEY not set. Required for Claude API access."
                )

            github_token = os.environ.get("GITHUB_TOKEN", "")
            if not github_token:
                warnings.append(
                    "GITHUB_TOKEN not set. GitHub operations will fail."
                )

        # Check for common misconfigs
        repo = os.environ.get("SWARM_GITHUB_REPO", "")
        if repo and "/" not in repo:
            errors.append(
                f"SWARM_GITHUB_REPO='{repo}' is invalid. Expected 'owner/repo' format."
            )

        external_url = os.environ.get("EXTERNAL_URL", "")
        if external_url and not external_url.startswith("http"):
            warnings.append(
                f"EXTERNAL_URL='{external_url}' doesn't start with http. "
                "Mattermost callbacks may fail."
            )

        mm_token = os.environ.get("SWARM_PO_MATTERMOST_TOKEN", "")
        if not mm_token and not os.environ.get("MATTERMOST_BOT_TOKEN", ""):
            warnings.append(
                "No Mattermost token set. Chat integration will be disabled."
            )

        return ValidationResult(
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def validate_and_log(self, require_api_keys: bool = True) -> ValidationResult:
        result = self.validate(require_api_keys)
        for w in result.warnings:
            log.warning("Startup warning: %s", w)
        for e in result.errors:
            log.error("Startup error: %s", e)
        if result.ok:
            log.info("Startup validation passed")
        else:
            log.error("Startup validation failed with %d error(s)", len(result.errors))
        return result
