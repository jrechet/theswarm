"""A request — a customer's need in their own words (V3 M5)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

RECEIVED = "received"
PLANNED = "planned"
BUILDING = "building"
DELIVERED = "delivered"
DECLINED = "declined"
STEPS = (RECEIVED, PLANNED, BUILDING, DELIVERED)
STEP_LABELS = {RECEIVED: "Received", PLANNED: "Planned", BUILDING: "Building", DELIVERED: "Delivered"}
TITLE_MAX = 120


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Request:
    """What a member asked for, and where it stands.

    ``received`` → ``planned`` (the owner made a feature of it: the
    repository and the issue) → ``building`` (a cycle started on that
    issue) → ``delivered`` (that cycle's demo); or ``declined`` with a
    reason. Frozen: every change returns a copy.
    """

    id: str
    customer_id: str
    title: str
    body: str = ""
    project_id: str = ""
    member_id: str = ""
    author_name: str = ""
    status: str = RECEIVED
    feature_repo: str = ""
    feature_issue_number: int | None = None
    demo_report_id: str = ""
    decline_reason: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @property
    def step(self) -> int:
        """0..3 along received → delivered; -1 when declined."""
        return STEPS.index(self.status) if self.status in STEPS else -1

    @property
    def is_open(self) -> bool:
        return self.status in (RECEIVED, PLANNED, BUILDING)

    def steps(self) -> list[dict]:
        """The four chips of the member's view: done, now, next — or declined."""
        rows = []
        for i, key in enumerate(STEPS):
            if self.status == DECLINED:
                state = "done" if i == 0 else "off"
            elif i < self.step:
                state = "done"
            elif i == self.step:
                state = "now"
            else:
                state = "next"
            rows.append({"key": key, "label": STEP_LABELS[key], "state": state})
        return rows

    def planned(self, repo: str, issue_number: int, project_id: str = "", now: datetime | None = None) -> Request:
        return replace(self, status=PLANNED, feature_repo=repo, feature_issue_number=issue_number,
                       project_id=project_id or self.project_id, updated_at=now or _now())

    def building(self, now: datetime | None = None) -> Request:
        """A cycle started on the feature; the same request twice is itself."""
        if self.status != PLANNED:
            return self
        return replace(self, status=BUILDING, updated_at=now or _now())

    def delivered(self, report_id: str, now: datetime | None = None) -> Request:
        """The feature's demo landed; a later demo of the same feature replaces it."""
        if self.status not in (PLANNED, BUILDING, DELIVERED):
            return self
        if self.status == DELIVERED and (not report_id or report_id == self.demo_report_id):
            return self
        return replace(self, status=DELIVERED, demo_report_id=report_id or self.demo_report_id,
                       updated_at=now or _now())

    def declined(self, reason: str = "", now: datetime | None = None) -> Request:
        return replace(self, status=DECLINED, decline_reason=reason.strip(), updated_at=now or _now())
