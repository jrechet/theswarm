"""Flow templates (phase B, B3) — the owner's decision of 2026-11-15:
templates with insertion points, not a free canvas.

What makes a cycle deliver lives in the roles' code: a PR merges on green CI
only, the working tree is the truth, one review per PR head. A graph where
the review or QA can be removed makes teams that no longer ship. So a cycle
follows one of a few flows, each a path through the same durable graph:

- **feature** — the whole of it: the TechLead breaks the feature into tasks,
  the Dev builds them, each PR is reviewed and merged, QA films the result,
  the PO reports.
- **fix** — one task, no breakdown: the issue *is* the task. Dev → review →
  QA on what was merged. No plan, no evening report.
- **review** — nothing is built: the feature's open PRs are reviewed and
  merged, and the cycle ends.

**The flow is a label on the issue** (`flow:fix`, `flow:review`; none is
feature). Hand-offs in the swarm are GitHub states — `status:*`, `Parent:`,
the review status — and the flow is one more: a resume after a deploy, a
cycle waiting in the queue, the `swarm:go` label door and a Play all read
the same place, and no table has to follow the cycle around.
"""

from __future__ import annotations

from dataclasses import dataclass

FEATURE, FIX, REVIEW = "feature", "fix", "review"
LABEL_PREFIX = "flow:"


@dataclass(frozen=True)
class FlowTemplate:
    key: str
    name: str
    what: str
    # the cycle graph's nodes this flow goes through, in order (the dev loop
    # is `dev_iter` ⇄ `techlead_review`)
    path: tuple[str, ...]
    # where a free persona may be inserted (B3, second half), by name
    insertion_points: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return "" if self.key == FEATURE else f"{LABEL_PREFIX}{self.key}"


TEMPLATES: tuple[FlowTemplate, ...] = (
    FlowTemplate(
        FEATURE, "Feature", "Break it into tasks, build each, review, film the result, report.",
        ("prepare", "po_morning", "techlead_breakdown", "dev_iter", "techlead_review", "dev_loop_end", "qa",
         "po_evening", "merge_held", "finish", "cycle_log"),
        ("before_dev", "before_merge", "after_qa"),
    ),
    FlowTemplate(
        FIX, "Fix", "One task, no breakdown: build it, review it, check what was merged.",
        ("prepare", "fix_intake", "dev_iter", "techlead_review", "dev_loop_end", "qa", "merge_held", "finish",
         "cycle_log"),
        ("before_merge", "after_qa"),
    ),
    FlowTemplate(
        REVIEW, "Review only", "Build nothing: review this feature's open pull requests and merge the good ones.",
        ("prepare", "techlead_review", "dev_loop_end", "merge_held", "finish", "cycle_log"),
        ("before_merge",),
    ),
)
TEMPLATE_KEYS: tuple[str, ...] = tuple(t.key for t in TEMPLATES)
_BY_KEY = {t.key: t for t in TEMPLATES}


def template(key: str | None) -> FlowTemplate:
    """The flow called `key`; the feature flow for anything else."""
    return _BY_KEY.get(str(key or ""), _BY_KEY[FEATURE])


def flow_of_labels(labels) -> str:
    """The flow an issue's labels ask for: `flow:fix`, `flow:review`, else feature."""
    names = {(label if isinstance(label, str) else (label or {}).get("name", "")) for label in labels or []}
    for candidate in TEMPLATES:
        if candidate.label and candidate.label in names:
            return candidate.key
    return FEATURE


def flow_labels() -> tuple[str, ...]:
    return tuple(t.label for t in TEMPLATES if t.label)
