"""Domain events for the Agents bounded context."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.events import DomainEvent


@dataclass(frozen=True)
class RoleAssigned(DomainEvent):
    project_id: str = ""
    role: str = ""
    codename: str = ""
    assignment_id: str = ""


@dataclass(frozen=True)
class RoleRetired(DomainEvent):
    project_id: str = ""
    role: str = ""
    codename: str = ""
    assignment_id: str = ""
