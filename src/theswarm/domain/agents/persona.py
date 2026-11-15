"""A persona: what the owner says a role is on this instance or this project.

Phase B, B1 — "le persona est une donnée". The four engine roles (and
DevOps) keep their code; what the owner sets is who they are in words: a
name, a description, instructions that enter every prompt of that role, and
optionally the model and effort it runs on for one project. Everything left
empty inherits (`PersonaService.team`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.agents.roles import ROLE_KEYS
from theswarm.domain.agents.settings import EFFORT_KEYS, MODEL_KEYS

NAME_MAX = 60
DESCRIPTION_MAX = 300
INSTRUCTIONS_MAX = 4000
INSTANCE = ""  # the scope of the instance's default team


class PersonaError(ValueError):
    """A persona that cannot be saved, said in words for the owner."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Persona:
    scope: str
    key: str
    name: str = ""
    description: str = ""
    instructions: str = ""
    model: str = ""
    effort: str = ""
    updated_by: str = ""
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.key not in ROLE_KEYS:
            raise PersonaError(f"no role called {self.key!r}")
        if self.scope and self.scope.count("/") != 1:
            raise PersonaError(f"{self.scope!r} is not a project (owner/name)")
        if len(self.name) > NAME_MAX:
            raise PersonaError(f"{self.key}: a name of {NAME_MAX} characters at most")
        if len(self.description) > DESCRIPTION_MAX:
            raise PersonaError(f"{self.key}: a description of {DESCRIPTION_MAX} characters at most")
        if len(self.instructions) > INSTRUCTIONS_MAX:
            raise PersonaError(f"{self.key}: instructions of {INSTRUCTIONS_MAX} characters at most")
        if self.model and self.model not in MODEL_KEYS:
            raise PersonaError(f"{self.model!r} is not one of {', '.join(MODEL_KEYS)}")
        if self.effort and self.effort not in EFFORT_KEYS:
            raise PersonaError(f"{self.effort!r} is not one of {', '.join(EFFORT_KEYS)}")

    @property
    def empty(self) -> bool:
        return not (self.name or self.description or self.instructions or self.model or self.effort)


@dataclass(frozen=True)
class TeamMember:
    """A role as a cycle of one project meets it: every field resolved."""
    key: str
    name: str
    description: str = ""
    instructions: str = ""
    model: str = ""   # "" — the instance's model
    effort: str = ""  # "" — Claude Code's own
    # where each word came from, for the page: "project", "instance" or "built-in"
    sources: dict = field(default_factory=dict)
