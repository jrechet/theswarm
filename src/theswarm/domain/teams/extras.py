"""Free personas: what the owner adds to a flow (phase B, B3, second half).

The four engine roles keep their code. A free persona is a prompt the owner
writes, run at one of a flow's **insertion points** with one of a few
**effects** — never a new edge of the graph, so no team can be drawn that
stops shipping:

- `before_merge` — on every pull request the TechLead approved, before it
  merges. Effect `comment` (its findings on the PR) or `block` (the PR goes
  back to the Dev with them, as a review's changes would).
- `after_qa` — once the feature is filmed. Effect `comment` (on the
  feature's issue): a changelog line, the documentation to update, a note
  for the customer.

A free persona **reads**: the repository and the pull request, never a
write. It answers a validated verdict; what it says changes the flow only
through its effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.agents.roles import ROLE_KEYS
from theswarm.domain.agents.settings import MODEL_KEYS

BEFORE_MERGE, AFTER_QA = "before_merge", "after_qa"
POINTS: tuple[tuple[str, str], ...] = (
    (BEFORE_MERGE, "Before the merge — on each approved pull request"),
    (AFTER_QA, "After QA — once the feature is filmed"),
)
COMMENT, BLOCK = "comment", "block"
EFFECTS: tuple[tuple[str, str], ...] = (
    (COMMENT, "Comment — say what it found"),
    (BLOCK, "Block — send the pull request back to the Dev"),
)
EFFECTS_AT = {BEFORE_MERGE: (COMMENT, BLOCK), AFTER_QA: (COMMENT,)}

NAME_MAX, PROMPT_MAX, MAX_PER_TEAM = 60, 4000, 6
_KEY = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class ExtraError(ValueError):
    """A free persona that cannot be saved, said in words for the owner."""


def key_from(name: str) -> str:
    """A key for a name: "Security reviewer" → "security-reviewer"."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")[:31]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Extra:
    scope: str
    key: str
    name: str
    prompt: str
    point: str
    effect: str = COMMENT
    model: str = ""
    enabled: bool = True
    updated_by: str = ""
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not _KEY.match(self.key):
            raise ExtraError(f"{self.key!r}: a key of lower-case letters, digits and dashes")
        if self.key in ROLE_KEYS:
            raise ExtraError(f"{self.key!r} is a role of the team — give this persona its own name")
        if self.scope and self.scope.count("/") != 1:
            raise ExtraError(f"{self.scope!r} is not a project (owner/name)")
        if not self.name.strip() or len(self.name) > NAME_MAX:
            raise ExtraError(f"A name, of {NAME_MAX} characters at most")
        if not self.prompt.strip() or len(self.prompt) > PROMPT_MAX:
            raise ExtraError(f"{self.name}: what it looks for, in {PROMPT_MAX} characters at most")
        if self.point not in EFFECTS_AT:
            raise ExtraError(f"{self.point!r} is not a point of the flow ({', '.join(EFFECTS_AT)})")
        if self.effect not in EFFECTS_AT[self.point]:
            raise ExtraError(f"{self.name}: at {self.point} a persona may {' or '.join(EFFECTS_AT[self.point])}, "
                             f"not {self.effect}")
        if self.model and self.model not in MODEL_KEYS:
            raise ExtraError(f"{self.model!r} is not one of {', '.join(MODEL_KEYS)}")

    def as_dict(self) -> dict:
        """What a cycle carries of it (values only: it is checkpointed with the team)."""
        return {"key": self.key, "name": self.name, "prompt": self.prompt, "point": self.point,
                "effect": self.effect, "model": self.model}
