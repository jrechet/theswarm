"""Shared helpers for all SWARM MVP agents."""

from __future__ import annotations

import logging
from typing import Any

from theswarm.config import AgentState, Role

log = logging.getLogger(__name__)


async def load_context(state: AgentState) -> dict[str, Any]:
    """Load GOLDEN_RULES + AGENT_MEMORY + DoD from the target repo."""
    github = state.get("github")
    if github is None:
        log.warning("No GitHub client — skipping context load")
        return {"context": "(no context — stub run)"}

    parts: list[str] = []
    for path in ("GOLDEN_RULES.md", "AGENT_MEMORY.md", "DOD.md"):
        try:
            content = await github.get_file_content(path)
            parts.append(content)
        except Exception:
            log.debug("Could not load %s", path)

    return {"context": "\n\n---\n\n".join(parts) if parts else "(empty context)"}


def stub_result(role: Role, phase: str, detail: str = "") -> dict[str, Any]:
    """Return a standard stub result for a phase that is not yet implemented."""
    msg = f"[STUB] {role.value}/{phase}: would execute here"
    if detail:
        msg += f" — {detail}"
    log.info(msg)
    return {"result": msg, "tokens_used": 0}
