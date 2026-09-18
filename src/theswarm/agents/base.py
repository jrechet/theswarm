"""Shared helpers for all SWARM MVP agents."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from theswarm.config import AgentState, Role

log = logging.getLogger(__name__)

# Cold install of a typical FastAPI stack measured 145s in the deploy
# container, so a 120s cap always expired.
DEP_INSTALL_TIMEOUT_SECONDS = 300


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


def find_system_python() -> str:
    """Interpreter used to install and run the *target* project's code.

    Deliberately not TheSwarm's own venv: the target project's dependencies
    must not be installed into it, and the venv ignores the user site-packages
    directory that a non-root ``pip install`` writes to. Dev and QA must agree
    on this — installing with one interpreter and testing with another means
    the tests never see the dependencies (prod cycle 882694d44248).
    """
    import os
    import sys as _sys

    venv_prefix = _sys.prefix
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if venv_prefix in entry:
            continue
        candidate = os.path.join(entry, "python3")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "python3"


def stub_result(role: Role, phase: str, detail: str = "") -> dict[str, Any]:
    """Return a standard stub result for a phase that is not yet implemented."""
    msg = f"[STUB] {role.value}/{phase}: would execute here"
    if detail:
        msg += f" — {detail}"
    log.info(msg)
    return {"result": msg, "tokens_used": 0}


# ── Target toolchain: install plan + runner detection ──────────────────
#
# Shared by the Dev and QA agents so both install the target the same way
# and agree on the same "tests didn't really run" signals. Before this, QA
# assumed the Dev had already installed the target — on a cycle where the
# Dev produced no PR (an ALREADY_SATISFIED answer, or nothing at all), QA
# ran pytest against a workspace with no dependencies installed, read the
# instant "No module named pytest" failure as a vacuous 0/0 pass, and then
# waited out a full readiness timeout per launch for a server that had
# already exited (cycle 5b1da00155c2).

# The test runner reporting its own absence. Not a test failure: nothing
# ran. Asking Claude to "fix the failing tests" here produced two repair
# rounds against a phantom, the second of which broke the syntax of the
# very file being edited (cycle f12107432167, #88).
_RUNNER_MISSING = ("No module named pytest", "No module named 'pytest'")

# pytest's own exit code for "collected nothing": the suite is empty, not red.
_PYTEST_NO_TESTS = 5


def _test_runner_missing(output: str, exit_code: int | None = None) -> str:
    """The reason the tests could not run at all, or "" when they did.

    `exit_code` is optional: the Dev's Ralph Loop treats an empty suite as
    a pass (nothing to retry against), so it never passes one and stays on
    the original text-only check. QA opts in by passing pytest's own exit
    code, so "collected nothing" reads as `not_run` there instead of a
    vacuous 0/0 pass.
    """
    for marker in _RUNNER_MISSING:
        if marker in output:
            return "pytest is not installed for the target interpreter"
    if exit_code == _PYTEST_NO_TESTS:
        return "no tests collected in the workspace"
    return ""


def _dev_dependencies(pyproject: dict) -> list[str]:
    """Dev/test requirement strings a pyproject declares.

    PEP 735 dependency groups first (what `uv sync --dev` reads), then the
    older optional-dependencies extras named dev/test. Only plain strings —
    a group may `{include-group = ...}` another, which pip cannot take."""
    found: list[str] = []
    groups = pyproject.get("dependency-groups", {}) or {}
    for name in ("dev", "test", "tests"):
        found += [d for d in groups.get(name, []) or [] if isinstance(d, str)]
    extras = (pyproject.get("project", {}) or {}).get("optional-dependencies", {}) or {}
    for name in ("dev", "test", "tests"):
        found += [d for d in extras.get(name, []) or [] if isinstance(d, str)]
    return list(dict.fromkeys(found))


def _install_plan(workspace: str, python: str) -> tuple[list[list[str]], str]:
    """(pip commands to run, fingerprint of what they depend on).

    requirements.txt wins when present: the path every target so far took.
    A pyproject project — TheSwarm itself is one — gets installed editable
    with its dev group, so `python -m pytest` finds both the package and
    the runner. Neither file: nothing to install, empty fingerprint.
    """
    req_file = os.path.join(workspace, "requirements.txt")
    if os.path.isfile(req_file):
        return (
            [[python, "-m", "pip", "install", "-q", "-r", "requirements.txt"]],
            _requirements_fingerprint(req_file),
        )
    pyproject_file = os.path.join(workspace, "pyproject.toml")
    if not os.path.isfile(pyproject_file):
        return [], ""
    import tomllib

    digest = hashlib.sha256()
    try:
        with open(pyproject_file, "rb") as handle:
            raw = handle.read()
        digest.update(raw)
        pyproject = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("pyproject.toml unreadable (%s) — installing nothing", exc)
        return [], ""
    lock = os.path.join(workspace, "uv.lock")
    if os.path.isfile(lock):
        with open(lock, "rb") as handle:
            digest.update(handle.read())
    command = [python, "-m", "pip", "install", "-q", "-e", ".", *_dev_dependencies(pyproject)]
    return [command], digest.hexdigest()


def _requirements_fingerprint(req_file: str) -> str:
    """Content hash of requirements.txt, or "" when there is no file.

    Keyed on content rather than a boolean so a Ralph Loop retry that adds a
    missing dependency triggers a reinstall, while repeated retries over
    unchanged requirements still skip the expensive install.
    """
    try:
        with open(req_file, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


async def install_target(
    workspace: str, python: str, claude, deps_fingerprint: str,
    *, timeout: int = DEP_INSTALL_TIMEOUT_SECONDS,
) -> str:
    """Install the target the way its toolchain declares, unless nothing changed.

    Returns the fingerprint of what the workspace now has installed —
    unchanged from `deps_fingerprint` when the install was skipped. Callers
    thread this back into `deps_fingerprint` in their own state so a retry
    (Dev's Ralph Loop) or a second phase on the same workspace (QA, right
    after Dev) doesn't pay for a reinstall of what's already there.
    """
    commands, fingerprint = _install_plan(workspace, python)
    if fingerprint and fingerprint != deps_fingerprint:
        for command in commands:
            install_result = await claude.run_tests(workspace, command, timeout=timeout)
            if not install_result["passed"]:
                log.warning("dependency install failed:\n%s", install_result["output"][-1000:])
    return fingerprint
