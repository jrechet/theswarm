"""Every key a graph node hands to a later node must be in AgentState.

LangGraph builds its channels from the state schema and silently discards
returned keys the schema does not declare. Two prod bugs came from this:
``retry_count`` (dev loop retried forever, cycle 65ab4b0fdf3e) and
``video_artifacts`` (demo videos never reached the report). This test
guards the whole class rather than the two known instances.
"""

from __future__ import annotations

import ast
import pathlib

from theswarm.config import AgentState

AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "src" / "theswarm" / "agents"

# Keys returned by plain helper functions rather than graph nodes. These are
# collected into a declared key (e.g. reviews) instead of flowing through the
# graph state, so the schema does not need them.
HELPER_ONLY_KEYS = {"decision", "summary", "issues", "pr_number"}


def _returned_dict_keys(path: pathlib.Path) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys.update(
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            )
    return keys


def test_no_agent_returns_an_undeclared_state_key():
    declared = set(AgentState.__annotations__)
    undeclared: dict[str, set[str]] = {}

    for path in sorted(AGENTS_DIR.glob("*.py")):
        for key in _returned_dict_keys(path) - declared - HELPER_ONLY_KEYS:
            undeclared.setdefault(key, set()).add(path.name)

    assert not undeclared, (
        "These keys are returned by agent code but missing from AgentState, so "
        f"LangGraph will drop them on state merge: {undeclared}"
    )


def test_known_regressions_stay_declared():
    """Explicit guards for the two keys that were dropped in production."""
    declared = set(AgentState.__annotations__)
    assert "retry_count" in declared
    assert "video_artifacts" in declared
