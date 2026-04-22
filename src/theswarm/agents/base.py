"""Shared helpers for all SWARM MVP agents."""

from __future__ import annotations

import logging
from typing import Any

from theswarm.config import AgentState, Role

log = logging.getLogger(__name__)


async def load_context(state: AgentState) -> dict[str, Any]:
    """Load GOLDEN_RULES + relevant agent memory + DoD from the target repo.

    Memory is now role-aware: each agent gets the categories most relevant
    to its work, formatted as structured entries rather than raw markdown.
    """
    github = state.get("github")

    phase = state.get("phase", "")
    role = _infer_role(phase)
    codenames = state.get("codenames") or {}
    project_id = state.get("project_id") or state.get("team_id") or ""
    codename = codenames.get(role) if role else None

    persona = _build_persona_preamble(role, codename, project_id)

    if github is None:
        log.warning("No GitHub client — skipping context load")
        context = persona or "(no context — stub run)"
        return {"context": context}

    parts: list[str] = []
    if persona:
        parts.append(persona)

    # Load static docs
    for path in ("GOLDEN_RULES.md", "DOD.md"):
        try:
            content = await github.get_file_content(path)
            parts.append(content)
        except Exception:
            log.debug("Could not load %s", path)

    # Load structured memory (role-aware)
    try:
        from theswarm.memory_store import load_entries, query, format_for_prompt
        entries = await load_entries(github)
        relevant = query(entries, role=role, limit=25)
        memory_text = format_for_prompt(relevant, max_chars=3000)
        parts.append(f"## Agent Memory\n\n{memory_text}")
    except Exception:
        # Fall back to legacy AGENT_MEMORY.md
        try:
            content = await github.get_file_content("AGENT_MEMORY.md")
            parts.append(content)
        except Exception:
            log.debug("Could not load agent memory")

    context = "\n\n---\n\n".join(parts) if parts else "(empty context)"

    # Condense if context exceeds threshold
    try:
        from theswarm.tools.condenser import ContextCondenser
        condenser = ContextCondenser()
        result = await condenser.condense(context)
        context = result.condensed_text
    except Exception:
        log.debug("Context condensation skipped (not available or failed)")

    return {"context": context}


def _build_persona_preamble(
    role: str | None, codename: str | None, project_id: str,
) -> str:
    """Return a short persona line so the agent knows who it is."""
    if not role:
        return ""
    if codename:
        line = (
            f"## Persona\n\n"
            f"You are **{codename}**, the {role.upper()} on project `{project_id}`. "
            f"Sign your outputs as {codename} and speak in the first person."
        )
    else:
        line = (
            f"## Persona\n\n"
            f"You are the {role.upper()} on project `{project_id or 'default'}`."
        )
    return line


def _infer_role(phase: str) -> str | None:
    """Infer the agent role from the current phase for memory filtering."""
    phase_role_map = {
        "morning": "po",
        "evening": "po",
        "breakdown": "techlead",
        "review_loop": "techlead",
        "development": "dev",
        "demo": "qa",
    }
    return phase_role_map.get(phase)


def stub_result(role: Role, phase: str, detail: str = "") -> dict[str, Any]:
    """Return a standard stub result for a phase that is not yet implemented."""
    msg = f"[STUB] {role.value}/{phase}: would execute here"
    if detail:
        msg += f" — {detail}"
    log.info(msg)
    return {"result": msg, "tokens_used": 0}
