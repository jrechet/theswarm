"""Value objects for the Scheduling bounded context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    WEBHOOK = "webhook"


_CRON_RE = re.compile(
    r"^(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)\s+"
    r"(\*|[0-9,\-\/]+)$"
)


@dataclass(frozen=True)
class CronExpression:
    """A validated cron expression (5 fields: min hour dom month dow)."""

    value: str

    def __post_init__(self) -> None:
        if not _CRON_RE.match(self.value.strip()):
            raise ValueError(f"Invalid cron expression: {self.value!r}")

    def __str__(self) -> str:
        return self.value
