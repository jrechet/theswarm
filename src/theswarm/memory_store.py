"""Living Memory — structured JSONL memory with query, retrospective, and compaction.

Replaces the append-only AGENT_MEMORY.md with a queryable, self-refining memory
stored as AGENT_MEMORY.jsonl in the target repo. Each entry is typed, timestamped,
and confidence-scored. Agents query relevant memory before acting and contribute
learnings after each cycle.

Migration: reads legacy AGENT_MEMORY.md on first load, converts to JSONL entries.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

MEMORY_JSONL_PATH = "AGENT_MEMORY.jsonl"
LEGACY_MEMORY_PATH = "AGENT_MEMORY.md"

# Memory categories (superset of the old markdown sections)
CATEGORIES = (
    "stack",          # Stack technique — tools, versions, patterns
    "conventions",    # Conventions de code — formatting, naming, project rules
    "errors",         # Erreurs à éviter — known pitfalls, anti-patterns
    "architecture",   # Décisions architecturales — design choices, tradeoffs
    "learnings",      # Cross-cycle insights from retrospectives
)

# Map legacy markdown headings to new categories
_LEGACY_CATEGORY_MAP = {
    "Stack technique": "stack",
    "Conventions de code": "conventions",
    "Erreurs à éviter": "errors",
    "Décisions architecturales": "architecture",
}

# Which categories are most relevant to each agent role
ROLE_CATEGORIES: dict[str, list[str]] = {
    "po": ["architecture", "learnings"],
    "techlead": ["conventions", "architecture", "errors", "learnings"],
    "dev": ["conventions", "stack", "errors"],
    "qa": ["stack", "errors", "learnings"],
}


def make_entry(
    category: str,
    content: str,
    agent: str,
    *,
    confidence: float = 1.0,
    cycle_date: str = "",
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Create a memory entry dict."""
    return {
        "id": uuid.uuid4().hex[:12],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "category": category,
        "agent": agent,
        "content": content,
        "confidence": round(confidence, 2),
        "cycle_date": cycle_date or datetime.now().strftime("%Y-%m-%d"),
        "supersedes": supersedes,
    }


def _parse_jsonl(raw: str) -> list[dict]:
    """Parse JSONL text into a list of entry dicts."""
    entries = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("Memory: skipping malformed JSONL line: %s", line[:80])
    return entries


def _entries_to_jsonl(entries: list[dict]) -> str:
    """Serialize entries to JSONL text."""
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"


def _migrate_legacy_md(md_content: str) -> list[dict]:
    """Convert legacy AGENT_MEMORY.md entries to structured JSONL entries."""
    entries = []
    current_category = None

    for line in md_content.splitlines():
        stripped = line.strip()

        # Detect section headings
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            current_category = _LEGACY_CATEGORY_MAP.get(heading)
            continue

        # Skip placeholders and empty lines
        if not stripped or stripped.startswith("_(") or stripped.startswith("# "):
            continue

        # Parse entry lines like: - [2026-04-06] (QA) some content
        if stripped.startswith("- ") and current_category:
            content = stripped[2:]
            # Try to extract agent from (role) prefix
            agent = "unknown"
            if "(" in content and ")" in content:
                paren_start = content.index("(")
                paren_end = content.index(")")
                # Check if it's right after a date bracket
                if content[:paren_start].strip().endswith("]"):
                    agent = content[paren_start + 1:paren_end]
                    content = content[paren_end + 1:].strip()
                    # Strip the date prefix
                    if content.startswith("[") and "]" in content:
                        content = content[content.index("]") + 1:].strip()
                    elif content[:paren_start].strip().startswith("["):
                        date_part = content[:paren_start].strip()
                        content = content[paren_end + 1:].strip()

            # Strip leading date bracket if still present
            if content.startswith("[") and "]" in content:
                bracket_end = content.index("]")
                content = content[bracket_end + 1:].strip()

            if content:
                entries.append(make_entry(
                    category=current_category,
                    content=content,
                    agent=agent,
                    confidence=0.7,  # legacy entries get lower confidence
                ))

    return entries


async def load_entries(github, *, ref: str = "main") -> list[dict]:
    """Load memory entries from the repo. Tries JSONL first, falls back to legacy MD."""
    # Try JSONL first
    try:
        raw = await github.get_file_content(MEMORY_JSONL_PATH, ref=ref)
        return _parse_jsonl(raw)
    except Exception:
        pass

    # Fall back to legacy markdown
    try:
        md = await github.get_file_content(LEGACY_MEMORY_PATH, ref=ref)
        entries = _migrate_legacy_md(md)
        if entries:
            log.info("Memory: migrated %d entries from legacy AGENT_MEMORY.md", len(entries))
        return entries
    except Exception:
        return []


async def save_entries(
    github,
    entries: list[dict],
    *,
    branch: str = "main",
    message: str = "chore: update agent memory",
) -> bool:
    """Write all entries to AGENT_MEMORY.jsonl in the repo."""
    try:
        content = _entries_to_jsonl(entries)
        await github.update_file(
            MEMORY_JSONL_PATH,
            content,
            branch=branch,
            commit_message=message,
        )
        return True
    except Exception:
        log.exception("Memory: failed to save entries")
        return False


async def append_entries(
    github,
    new_entries: list[dict],
    *,
    branch: str = "main",
) -> bool:
    """Append new entries to existing memory."""
    if not new_entries:
        return True

    existing = await load_entries(github)
    combined = existing + new_entries

    agents = {e["agent"] for e in new_entries}
    categories = {e["category"] for e in new_entries}
    msg = f"chore: update agent memory [{', '.join(sorted(categories))}] — {', '.join(sorted(agents))}"

    return await save_entries(github, combined, branch=branch, message=msg)


def query(
    entries: list[dict],
    *,
    categories: list[str] | None = None,
    keywords: list[str] | None = None,
    role: str | None = None,
    min_confidence: float = 0.3,
    limit: int = 20,
) -> list[dict]:
    """Query memory entries by category, keywords, or role relevance.

    Returns entries sorted by relevance (confidence * recency).
    """
    # Filter by role's relevant categories if specified
    if role and not categories:
        categories = ROLE_CATEGORIES.get(role.lower(), list(CATEGORIES))

    results = []
    for entry in entries:
        # Skip low-confidence entries
        if entry.get("confidence", 1.0) < min_confidence:
            continue

        # Filter by category
        if categories and entry.get("category") not in categories:
            continue

        # Filter by keywords (any keyword in content)
        if keywords:
            content_lower = entry.get("content", "").lower()
            if not any(kw.lower() in content_lower for kw in keywords):
                continue

        results.append(entry)

    # Sort by confidence descending, then by timestamp descending
    results.sort(key=lambda e: (e.get("confidence", 0), e.get("timestamp", "")), reverse=True)

    return results[:limit]


def format_for_prompt(entries: list[dict], *, max_chars: int = 3000) -> str:
    """Format memory entries as context text for an agent prompt."""
    if not entries:
        return "(no memory entries)"

    # Group by category
    by_category: dict[str, list[dict]] = {}
    for e in entries:
        cat = e.get("category", "other")
        by_category.setdefault(cat, []).append(e)

    parts = []
    total = 0
    cat_labels = {
        "stack": "Stack & Tools",
        "conventions": "Code Conventions",
        "errors": "Known Pitfalls",
        "architecture": "Architecture Decisions",
        "learnings": "Cross-cycle Learnings",
    }

    for cat in CATEGORIES:
        cat_entries = by_category.get(cat, [])
        if not cat_entries:
            continue

        label = cat_labels.get(cat, cat)
        section = f"### {label}\n"
        for e in cat_entries:
            line = f"- {e['content']}\n"
            if total + len(section) + len(line) > max_chars:
                break
            section += line
            total += len(line)

        parts.append(section)
        if total > max_chars:
            break

    return "\n".join(parts) if parts else "(no memory entries)"


# ── Retrospective ─────────────────────────────────────────────────────


RETRO_SYSTEM = """\
You are analyzing a development cycle to extract learnings for the team's \
shared memory. Be specific and actionable. Each learning should be one sentence \
that a developer can act on immediately.

Return ONLY a JSON array of objects. No prose, no markdown fences.
"""

RETRO_PROMPT = """\
## Cycle results

Date: {date}
Cost: ${cost:.2f}
PRs opened: {prs_opened}
PRs merged: {prs_merged}

## Reviews with issues
{review_issues}

## Test results
{test_summary}

## Current memory (for dedup)
{current_memory}

## Instructions

Extract 2-5 learnings from this cycle. Each learning should be:
- Specific and actionable (not generic advice)
- New (not already in current memory)
- Categorized as: stack, conventions, errors, architecture, or learnings

Return JSON:
[
    {{"category": "errors", "content": "Always check for None before accessing .items() on GitHub API responses", "confidence": 0.9}},
    ...
]

If nothing new was learned, return an empty array: []
"""


async def run_retrospective(
    github,
    claude,
    cycle_result: dict,
    existing_entries: list[dict] | None = None,
) -> list[dict]:
    """Run a Claude-powered retrospective to extract learnings from a cycle.

    Returns new memory entries (not yet saved).
    """
    if existing_entries is None:
        existing_entries = await load_entries(github)

    # Build review issues summary
    reviews = cycle_result.get("reviews", [])
    review_issues = []
    for r in reviews:
        if r.get("decision") == "REQUEST_CHANGES":
            issues = r.get("issues", [])
            for issue in issues[:3]:
                review_issues.append(
                    f"- PR #{r['pr_number']}: {issue.get('description', 'review issue')[:150]}"
                )

    # Build test summary
    demo = cycle_result.get("demo_report", {})
    gates = demo.get("quality_gates", {}) if demo else {}
    test_parts = []
    for gate_name, gate_data in gates.items():
        status = gate_data.get("status", "unknown")
        test_parts.append(f"- {gate_name}: {status}")

    # Format existing memory for dedup
    memory_summary = "\n".join(
        f"- [{e.get('category')}] {e.get('content', '')[:100]}"
        for e in existing_entries[-30:]  # last 30 for context
    ) or "(empty memory)"

    prompt = RETRO_PROMPT.format(
        date=cycle_result.get("date", "unknown"),
        cost=cycle_result.get("cost_usd", 0.0),
        prs_opened=len(cycle_result.get("prs", [])),
        prs_merged=sum(1 for r in reviews if r.get("decision") == "APPROVE"),
        review_issues="\n".join(review_issues) or "(none)",
        test_summary="\n".join(test_parts) or "(no test data)",
        current_memory=memory_summary,
    )

    try:
        result = await claude.run(prompt, timeout=60)
        raw = result.text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            import re
            raw = re.sub(r"^```\w*\n", "", raw)
            raw = re.sub(r"\n```\s*$", "", raw)

        learnings = json.loads(raw)
        if not isinstance(learnings, list):
            return []

        cycle_date = cycle_result.get("date", datetime.now().strftime("%Y-%m-%d"))
        new_entries = []
        for item in learnings:
            cat = item.get("category", "learnings")
            if cat not in CATEGORIES:
                cat = "learnings"
            new_entries.append(make_entry(
                category=cat,
                content=item.get("content", ""),
                agent="retrospective",
                confidence=item.get("confidence", 0.8),
                cycle_date=cycle_date,
            ))

        log.info("Retrospective: extracted %d learnings", len(new_entries))
        return new_entries

    except (json.JSONDecodeError, Exception):
        log.exception("Retrospective: failed to parse learnings")
        return []


# ── Compaction ────────────────────────────────────────────────────────


COMPACT_PROMPT = """\
You are compacting a team's shared memory. The memory has grown large and \
contains redundant, outdated, or contradictory entries. Your job is to \
produce a clean, minimal set of entries that preserves all useful knowledge.

## Current memory entries (JSONL)
{entries_json}

## Instructions

For each category, produce a compacted set of entries:
1. Merge entries that say the same thing
2. Remove entries that are no longer true (superseded by newer entries)
3. Keep the highest-confidence version when entries conflict
4. Preserve specific, actionable entries over vague ones
5. Keep entries from the last 7 days even if they seem redundant

Return a JSON array of compacted entries. Each entry:
{{"category": "...", "content": "...", "confidence": 0.0-1.0}}

Return ONLY the JSON array. No prose.
"""


async def compact_memory(
    github,
    claude,
    *,
    branch: str = "main",
    threshold: int = 50,
) -> bool:
    """Compact memory if it exceeds threshold entries.

    Uses Claude to merge, deduplicate, and clean entries.
    Returns True if compaction ran, False if not needed or failed.
    """
    entries = await load_entries(github)
    if len(entries) < threshold:
        log.info("Memory: %d entries, below threshold %d — skipping compaction", len(entries), threshold)
        return False

    log.info("Memory: %d entries, running compaction (threshold=%d)", len(entries), threshold)

    # Format entries for Claude
    entries_text = "\n".join(
        json.dumps({"category": e["category"], "content": e["content"],
                     "confidence": e.get("confidence", 1.0),
                     "timestamp": e.get("timestamp", ""),
                     "agent": e.get("agent", "")},
                    ensure_ascii=False)
        for e in entries
    )

    prompt = COMPACT_PROMPT.format(entries_json=entries_text)

    try:
        result = await claude.run(prompt, timeout=90)
        raw = result.text.strip()

        if raw.startswith("```"):
            import re
            raw = re.sub(r"^```\w*\n", "", raw)
            raw = re.sub(r"\n```\s*$", "", raw)

        compacted_raw = json.loads(raw)
        if not isinstance(compacted_raw, list):
            log.warning("Compaction: unexpected response type")
            return False

        # Rebuild proper entries from compacted output
        cycle_date = datetime.now().strftime("%Y-%m-%d")
        compacted = []
        for item in compacted_raw:
            cat = item.get("category", "learnings")
            if cat not in CATEGORIES:
                cat = "learnings"
            compacted.append(make_entry(
                category=cat,
                content=item.get("content", ""),
                agent="compaction",
                confidence=item.get("confidence", 0.8),
                cycle_date=cycle_date,
            ))

        if not compacted:
            log.warning("Compaction: produced empty result, keeping original")
            return False

        saved = await save_entries(
            github, compacted, branch=branch,
            message=f"chore: compact agent memory ({len(entries)} → {len(compacted)} entries)",
        )

        if saved:
            log.info("Memory compacted: %d → %d entries", len(entries), len(compacted))
        return saved

    except (json.JSONDecodeError, Exception):
        log.exception("Compaction: failed")
        return False
