"""Domain events for the Reporting bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.events import DomainEvent


@dataclass(frozen=True)
class DemoReady(DomainEvent):
    """A demo report is ready to be played.

    Emitted after a cycle completes and a DemoReport has been persisted.
    Consumed by the SSE hub (browser toast) and Mattermost gateway (DM).
    """

    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    report_id: str = ""
    play_url: str = ""
    title: str = ""
    thumbnail_url: str = ""


@dataclass(frozen=True)
class CycleBlocked(DomainEvent):
    """A cycle was prevented from starting (paused project, cap reached)."""

    project_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class StoryApproved(DomainEvent):
    """A reviewer approved a story from the demo player."""

    report_id: str = ""
    ticket_id: str = ""
    user: str = ""


@dataclass(frozen=True)
class StoryRejected(DomainEvent):
    """A reviewer rejected a story from the demo player."""

    report_id: str = ""
    ticket_id: str = ""
    user: str = ""
    comment: str = ""


@dataclass(frozen=True)
class StoryCommented(DomainEvent):
    """A reviewer posted an inline comment on a story from the demo player."""

    report_id: str = ""
    ticket_id: str = ""
    user: str = ""
    comment: str = ""
