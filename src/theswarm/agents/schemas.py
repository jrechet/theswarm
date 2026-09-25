"""Structured outputs for the calls whose answer is consumed by code (V2, M3).

The SDK validates the answer against these schemas and re-prompts on a
mismatch; the agent receives a dict, never a piece of prose to grep. The
text parsers next to each call remain the CLI backend's fallback only —
the rollback path lives until M7 (invariant I13).

Kept flat and draft-07 friendly on purpose: no ``format``, optional fields
with defaults rather than unions, nested models only where a list of
records is the natural shape (the SDK accepts ``$defs``/``$ref``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_TASK_LABELS = ["role:dev", "status:ready"]


class BreakdownTask(BaseModel):
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=lambda: list(DEFAULT_TASK_LABELS))


class Breakdown(BaseModel):
    """The TechLead's split of one story into dev tasks."""

    tasks: list[BreakdownTask] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    severity: Literal["critical", "major", "minor", "nit"] = "minor"
    file: str = ""
    description: str = ""


class ReviewVerdict(BaseModel):
    """The TechLead's verdict on a pull request."""

    decision: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"]
    summary: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)


class FileBlock(BaseModel):
    path: str
    content: str


class DevOutcome(BaseModel):
    """What the Dev reports after an implementation or a Ralph retry.

    The tree stays the truth (I3): ``implemented`` is believed only when
    the workspace has work, ``already_satisfied`` only on a clean tree.
    ``files`` is the in-band replacement of the ``--- FILE:`` fallback for
    a file the model could not edit in place.
    """

    status: Literal["implemented", "already_satisfied", "blocked"]
    summary: str = ""
    reason: str = ""
    already_satisfied_file: str = ""
    files: list[FileBlock] = Field(default_factory=list)


class PlannedStory(BaseModel):
    number: int
    title: str = ""
    reason: str = ""


class DailyPlan(BaseModel):
    """The PO's morning pick: the stories to make ready, and the plan text.

    Parsed out of prose until 2026-09-25, when "PO: could not parse planning
    JSON, using raw text" left `selected` empty — nothing was made ready,
    and a non-targeted cycle's Dev had nothing to pick.
    """

    selected: list[PlannedStory] = Field(default_factory=list)
    daily_plan: str = ""

