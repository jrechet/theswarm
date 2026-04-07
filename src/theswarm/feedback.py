"""Auto-learning — extract lessons from human feedback and PR rejections.

When a human rejects a PR, comments on a report, or provides feedback,
this module analyzes the cause and generates high-confidence memory entries
that prevent the same mistake in future cycles.

Feedback loop: human comment → cause analysis → memory entry → better code.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


ANALYSIS_SYSTEM = """\
You are analyzing human feedback on an AI dev team's work to extract \
actionable lessons. Each lesson should prevent the same mistake from \
recurring. Be specific and concrete.

Return ONLY a JSON array. No prose, no markdown fences.
"""

ANALYSIS_PROMPT = """\
## Feedback context

A human reviewed the output of an autonomous AI dev team cycle and provided \
the following feedback:

### PR #{pr_number}: {pr_title}

**Review decision:** {decision}
**Review issues:**
{issues_text}

**Human comment (if any):**
{human_comment}

## Current team memory
{memory_summary}

## Instructions

Analyze this feedback and extract 1-3 lessons. Each lesson should:
1. Name the specific mistake or gap
2. State what should be done differently
3. Be categorized: conventions, errors, architecture, or stack

High confidence (0.9+) for clear, repeated patterns.
Medium confidence (0.7-0.8) for first-time issues.

Return JSON:
[
    {{"category": "conventions", "content": "Always add input validation on POST endpoints — reviewer flagged missing validation on /api/users", "confidence": 0.9}},
    ...
]

If no useful lessons can be extracted, return [].
"""


async def analyze_feedback(
    claude,
    pr_number: int,
    pr_title: str,
    decision: str,
    issues: list[dict],
    human_comment: str = "",
    existing_memory: list[dict] | None = None,
) -> list[dict]:
    """Analyze human feedback on a PR and return memory entries.

    Returns a list of dicts ready to be passed to memory_store.make_entry().
    """
    from theswarm.memory_store import CATEGORIES

    issues_text = "\n".join(
        f"- [{i.get('severity', 'info')}] {i.get('description', '')[:200]}"
        for i in issues
    ) or "(none)"

    memory_summary = "\n".join(
        f"- [{e.get('category')}] {e.get('content', '')[:100]}"
        for e in (existing_memory or [])[-20:]
    ) or "(empty)"

    prompt = ANALYSIS_PROMPT.format(
        pr_number=pr_number,
        pr_title=pr_title,
        decision=decision,
        issues_text=issues_text,
        human_comment=human_comment or "(no comment)",
        memory_summary=memory_summary,
    )

    try:
        result = await claude.run(prompt, timeout=60)
        raw = result.text.strip()

        # Strip markdown fences
        if raw.startswith("```"):
            import re
            raw = re.sub(r"^```\w*\n", "", raw)
            raw = re.sub(r"\n```\s*$", "", raw)

        lessons = json.loads(raw)
        if not isinstance(lessons, list):
            return []

        valid = []
        for item in lessons:
            cat = item.get("category", "learnings")
            if cat not in CATEGORIES:
                cat = "learnings"
            valid.append({
                "category": cat,
                "content": item.get("content", ""),
                "confidence": min(item.get("confidence", 0.8), 1.0),
            })

        log.info("Feedback analysis: extracted %d lessons from PR #%d", len(valid), pr_number)
        return valid

    except (json.JSONDecodeError, Exception):
        log.exception("Feedback analysis failed for PR #%d", pr_number)
        return []


async def process_cycle_feedback(
    github,
    claude,
    cycle_result: dict,
) -> list[dict]:
    """Process all feedback signals from a cycle and return memory entries.

    Signals analyzed:
    1. PRs with REQUEST_CHANGES decisions
    2. PRs with critical/major review issues
    3. Quality gate failures
    """
    from theswarm.memory_store import load_entries, make_entry

    existing = await load_entries(github)
    all_lessons: list[dict] = []
    reviews = cycle_result.get("reviews", [])

    for review in reviews:
        if review.get("decision") != "REQUEST_CHANGES":
            continue

        issues = review.get("issues", [])
        # Only analyze if there are real issues
        critical_or_major = [
            i for i in issues
            if i.get("severity", "").lower() in ("critical", "major")
        ]
        if not critical_or_major and not issues:
            continue

        lessons = await analyze_feedback(
            claude,
            pr_number=review.get("pr_number", 0),
            pr_title=review.get("pr_title", ""),
            decision=review["decision"],
            issues=issues,
            existing_memory=existing,
        )
        all_lessons.extend(lessons)

    # Quality gate failures
    demo = cycle_result.get("demo_report", {})
    if demo:
        gates = demo.get("quality_gates", {})
        for gate_name, gate_data in gates.items():
            if gate_data.get("status") == "fail":
                all_lessons.append({
                    "category": "errors",
                    "content": f"Quality gate '{gate_name}' failed — {json.dumps(gate_data)}",
                    "confidence": 0.7,
                })

    # Convert to memory entries
    cycle_date = cycle_result.get("date", "")
    entries = []
    for lesson in all_lessons:
        entries.append(make_entry(
            category=lesson["category"],
            content=lesson["content"],
            agent="feedback",
            confidence=lesson.get("confidence", 0.8),
            cycle_date=cycle_date,
        ))

    return entries


async def process_human_comment(
    claude,
    github,
    pr_number: int,
    comment: str,
) -> list[dict]:
    """Process a human comment on a PR and return memory entries.

    Called when a human uses the report comment form to provide feedback.
    """
    from theswarm.memory_store import load_entries, make_entry

    existing = await load_entries(github)

    lessons = await analyze_feedback(
        claude,
        pr_number=pr_number,
        pr_title="(from report comment)",
        decision="HUMAN_COMMENT",
        issues=[],
        human_comment=comment,
        existing_memory=existing,
    )

    entries = []
    for lesson in lessons:
        entries.append(make_entry(
            category=lesson["category"],
            content=lesson["content"],
            agent="feedback",
            confidence=lesson.get("confidence", 0.85),
        ))

    return entries
