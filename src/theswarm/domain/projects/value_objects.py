"""Value objects for the Projects bounded context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Framework(str, Enum):
    """Detected or configured project framework."""

    AUTO = "auto"
    FASTAPI = "fastapi"
    DJANGO = "django"
    FLASK = "flask"
    NEXTJS = "nextjs"
    EXPRESS = "express"
    GENERIC = "generic"


class TicketSourceType(str, Enum):
    """Supported ticket source backends."""

    GITHUB = "github"
    JIRA = "jira"
    LINEAR = "linear"
    GITLAB = "gitlab"


_REPO_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")


@dataclass(frozen=True)
class RepoUrl:
    """A validated owner/repo string."""

    value: str

    def __post_init__(self) -> None:
        if not _REPO_RE.match(self.value):
            raise ValueError(f"Invalid repo format: {self.value!r} (expected 'owner/repo')")

    @property
    def owner(self) -> str:
        return self.value.split("/")[0]

    @property
    def name(self) -> str:
        return self.value.split("/")[1]

    @property
    def https_clone_url(self) -> str:
        return f"https://github.com/{self.value}.git"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class FrameworkInfo:
    """Result of framework auto-detection."""

    framework: Framework
    test_command: str         # e.g. "pytest tests/"
    source_dir: str           # e.g. "src/"
    entry_point: str          # e.g. "src.main:app"
    default_branch: str       # e.g. "main"
