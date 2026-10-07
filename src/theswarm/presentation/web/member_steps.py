"""A member's view of a cycle: four plain steps, never the theater (V3 M5).

The owner reads the theater — the stepper of announced phases, the four
agents, the feed. A member reads the same cycle as Planning → Building →
Checking → Delivered, with one line of what is happening. `stage_for`
turns a cycle's last announced phase and its status into that view; it
is pure, so the customer overview and the feature page draw the same
thing.
"""

from __future__ import annotations

STEPS = (("plan", "Planning"), ("build", "Building"), ("check", "Checking"), ("deliver", "Delivered"))
PHASE_STEP = {
    "prepare": 0, "po_morning": 0, "techlead_breakdown": 0,
    "dev_loop": 1, "dev_iter": 1, "techlead_review": 1, "dev_loop_end": 1,
    "qa": 2,
    "po_evening": 3, "merge_held": 3, "finish": 3, "cycle_log": 3,
}
DETAILS = (
    "The team is reading the request and planning the work",
    "The code is being written and reviewed",
    "The build is being checked against the running app",
    "Wrapping up — the demo is on its way",
)
LIVE = ("running", "queued", "pending")
STOPPED = ("failed", "cancelled", "interrupted")


def _steps(states: list[str]) -> list[dict]:
    return [{"key": key, "label": label, "state": state} for (key, label), state in zip(STEPS, states)]


def _stage(key: str, headline: str, detail: str, live: bool, states: list[str]) -> dict:
    return {"key": key, "headline": headline, "detail": detail, "live": live, "steps": _steps(states)}


def stage_for(phase: str = "", status: str = "", *, has_demo: bool = False, closed: bool = False) -> dict:
    """What a member sees of a feature: the four steps and one line.

    `phase` is the cycle's last announced phase (empty when unknown),
    `status` the cycle's (empty when no cycle ran on the feature),
    `has_demo` whether its demo is stored, `closed` whether the issue is.
    """
    index = PHASE_STEP.get(phase, 0)
    if status in LIVE:
        return _stage("building", "Being built right now", DETAILS[index], True,
                      ["done"] * index + ["now"] + ["next"] * (3 - index))
    if status == "completed":
        if has_demo:
            return _stage("delivered", "Delivered", "The demo is ready to watch", False, ["done"] * 4)
        return _stage("finishing", "Almost there", "Built and checked — the demo is being prepared", True,
                      ["done", "done", "done", "now"])
    if status in STOPPED:
        return _stage("stopped", "Stopped before the end", "The team will pick it up again", False,
                      ["done"] * index + ["off"] + ["next"] * (3 - index))
    if closed:
        return _stage("delivered", "Delivered", "Done — shipped to the project", False, ["done"] * 4)
    return _stage("planned", "Planned", "Not started yet — the team will pick it up", False, ["next"] * 4)


PIECE_LABELS = {
    "done": "Done", "review": "Being reviewed", "in-progress": "In progress",
    "dropped": "Dropped", "ready": "Next up", "backlog": "To do",
}


def piece_label(status: str) -> str:
    """A sub-task's state in a member's words."""
    return PIECE_LABELS.get(status, "To do")
