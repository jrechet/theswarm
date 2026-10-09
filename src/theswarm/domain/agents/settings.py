"""Which Claude each persona runs on, and how hard it thinks — the owner's
choice, per instance (Settings → Agents).

A persona with no setting runs as before: the instance's model
(`SWARM_CLAUDE_MODEL`, Sonnet by default) and Claude Code's own effort. A
setting names a model alias (never a dated id) and an effort level, which
reaches Claude Code as `--effort`. Frozen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# The personas, in the order the theater draws them, and what each one's
# Claude calls are for (the page says so).
PERSONAS: tuple[tuple[str, str, str], ...] = (
    ("po", "Product Owner", "plans the day, reports in the evening, writes the customer's summary of a demo"),
    ("techlead", "Tech Lead", "breaks a feature into tasks, reviews every pull request"),
    ("dev", "Developer", "implements, retries on red tests, answers a review"),
    ("qa", "QA", "writes and repairs the end-to-end tests, triages failures, scripts the demo's calls"),
    ("devops", "DevOps", "proposes the improvement pull requests on the pipeline"),
)
PERSONA_KEYS = tuple(key for key, _, _ in PERSONAS)
MODELS: tuple[tuple[str, str], ...] = (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"))
MODEL_KEYS = tuple(key for key, _ in MODELS)
EFFORTS: tuple[tuple[str, str], ...] = (("low", "Low"), ("medium", "Medium"), ("high", "High"), ("max", "Max"))
EFFORT_KEYS = tuple(key for key, _ in EFFORTS)


class AgentSettingError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentSetting:
    persona: str
    model: str
    effort: str = ""  # "" leaves the effort to Claude Code
    updated_by: str = ""
    updated_at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.persona not in PERSONA_KEYS:
            raise AgentSettingError(f"no persona called {self.persona!r}")
        if self.model not in MODEL_KEYS:
            raise AgentSettingError(f"{self.model!r} is not one of {', '.join(MODEL_KEYS)}")
        if self.effort and self.effort not in EFFORT_KEYS:
            raise AgentSettingError(f"{self.effort!r} is not one of {', '.join(EFFORT_KEYS)}")
