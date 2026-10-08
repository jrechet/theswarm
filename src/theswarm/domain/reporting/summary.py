"""What the customer is told about a demo (V3 plan: "the PO writes the
customer-facing summary when a demo lands").

A demo report is for the people who built it: stories, gates, tests,
cost. The summary is for the person who asked: two or three plain
sentences on what they can now do, and — honestly — whether the running
app was checked. Written once when the demo lands, by the PO, kept beside
the report; a failed write is a `skipped` row with the reason, so the
owner sees why there is nothing and can ask again. Frozen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

WRITTEN = "written"
SKIPPED = "skipped"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DemoSummary:
    report_id: str
    status: str = WRITTEN
    headline: str = ""
    body: str = ""
    reason: str = ""
    written_by: str = "PO"
    created_at: datetime = field(default_factory=_now)

    @property
    def is_written(self) -> bool:
        return self.status == WRITTEN and bool(self.body)
