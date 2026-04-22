"""Dashboard chat thread + message entities (Phase B).

A ``ChatThread`` is scoped to a ``(project_id, codename)`` pair. When
``codename`` is empty the thread is the project-level team thread (posts
visible to all agents on that project). When ``project_id`` is the portfolio
sentinel it's a portfolio-wide thread.

``ChatMessage`` is append-only — edits are disallowed at the domain level;
any correction goes out as a new message that references ``reply_to``.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID


class AuthorKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True)
class ChatThread:
    id: str
    project_id: str
    codename: str = ""
    role: str = ""
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_message_at: datetime | None = None
    message_count: int = 0

    @property
    def is_portfolio(self) -> bool:
        return self.project_id == PORTFOLIO_PROJECT_ID

    @property
    def is_team_thread(self) -> bool:
        return self.codename == ""

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.is_team_thread:
            return f"{self.project_id} · team"
        return f"{self.codename} ({self.role.upper() or '?'})"

    @staticmethod
    def deterministic_id(project_id: str, codename: str = "") -> str:
        """Stable ID for ``(project_id, codename)`` so the UI can deep-link."""
        seed = f"{project_id}::{codename}".encode()
        digest = hashlib.sha256(seed).hexdigest()[:16]
        return f"th_{digest}"


@dataclass(frozen=True)
class ChatMessage:
    id: str
    thread_id: str
    author_kind: AuthorKind
    body: str
    author_id: str = ""
    author_display: str = ""
    intent_action: str = ""
    intent_confidence: float = 0.0
    reply_to: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return f"msg_{uuid.uuid4().hex[:12]}"
