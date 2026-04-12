"""Entities for the Chat bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.chat.value_objects import IntentAction


@dataclass(frozen=True)
class Persona:
    """A bot persona with its own name and known actions."""

    name: str
    display_name: str
    known_actions: tuple[IntentAction, ...] = ()
    help_text: str = ""

    def supports_action(self, action: IntentAction) -> bool:
        return action in self.known_actions


@dataclass(frozen=True)
class Conversation:
    """A conversation thread between a user and a persona."""

    user_id: str
    persona_name: str
    channel_id: str = ""
    project_id: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
