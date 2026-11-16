"""A first team for a project, drafted from what its repository says (phase B, B5).

"Crée une équipe pour ce projet": read the repository — its language, how
its tests run, its CI, what it declares for the demo — and write a team file
whose instructions are those facts, said to the role that needs them. No
Claude call: the draft is what a careful person would write after ten
minutes in the repository, and it is a *draft* — the agent that asked reads
it, changes it, and proposes it (`propose_team`); the owner accepts.

Nothing here is guessed: a fact that was not found is a line left out.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

# What is read, at most (one call each; a missing file is a fact too).
_FILES = ("pyproject.toml", "requirements.txt", "package.json", "go.mod", "Cargo.toml", "theswarm.yaml",
          "Makefile", ".github/workflows/ci.yml", ".github/workflows/ci.yaml", ".github/workflows/test.yml",
          "CONTRIBUTING.md", "GOLDEN_RULES.md")
_MAX_CHARS = 20_000


async def read_facts(github) -> dict:
    """What the repository says of itself: {file: text} for the files that exist."""
    found: dict[str, str] = {}
    for path in _FILES:
        try:
            text = await github.get_file_content(path)
        except Exception:  # noqa: BLE001 — absent, or unreadable: not a fact
            continue
        if isinstance(text, str) and text.strip():
            found[path] = text[:_MAX_CHARS]
    return found


def describe(files: dict[str, str]) -> dict:
    """The facts a team needs, each with the file it was read in."""
    facts: dict[str, str] = {}
    pyproject, package = files.get("pyproject.toml", ""), files.get("package.json", "")
    if pyproject or "requirements.txt" in files:
        facts["language"] = "Python"
        wanted = re.search(r'requires-python\s*=\s*"([^"]+)"', pyproject)
        if wanted:
            facts["python"] = wanted.group(1)
        if "pytest" in pyproject or "pytest" in files.get("requirements.txt", ""):
            facts["tests"] = "pytest"
        for tool in ("ruff", "black", "mypy"):
            if re.search(rf"\[tool\.{tool}\b", pyproject):
                facts.setdefault("lint", "")
                facts["lint"] = (facts["lint"] + ", " + tool).strip(", ")
        if "fastapi" in (pyproject + files.get("requirements.txt", "")).lower():
            facts["framework"] = "FastAPI"
    elif package:
        facts["language"] = "JavaScript/TypeScript"
        script = re.search(r'"test"\s*:\s*"([^"]+)"', package)
        if script:
            facts["tests"] = script.group(1)
    elif "go.mod" in files:
        facts["language"], facts["tests"] = "Go", "go test ./..."
    elif "Cargo.toml" in files:
        facts["language"], facts["tests"] = "Rust", "cargo test"
    ci = next((path for path in files if path.startswith(".github/workflows/")), "")
    if ci:
        facts["ci"] = ci
    if "theswarm.yaml" in files and re.search(r"(?m)^demo:", files["theswarm.yaml"]):
        facts["demo"] = "declared in theswarm.yaml"
    for rules in ("GOLDEN_RULES.md", "CONTRIBUTING.md"):
        if rules in files:
            facts["rules"] = rules
            break
    return facts


def draft(project: str, facts: dict) -> str:
    """A team file for `project` from the facts — valid by construction, and
    empty of any role nothing was learned about."""
    from theswarm.application.services import team_yaml
    from theswarm.domain.agents.persona import Persona

    said: dict[str, list[str]] = {"techlead": [], "dev": [], "qa": []}
    if facts.get("tests"):
        said["dev"].append(f"The tests run with {facts['tests']}; write the tests of your code first, and run them before you answer.")
        said["techlead"].append(f"Refuse a pull request whose new code has no test ({facts['tests']}).")
    if facts.get("lint"):
        said["dev"].append(f"The project checks its code with {facts['lint']}: leave it clean.")
    if facts.get("python"):
        said["dev"].append(f"The project requires Python {facts['python']}: use nothing newer.")
    if facts.get("framework"):
        said["dev"].append(f"It is a {facts['framework']} application: follow the routers, schemas and services already there.")
    if facts.get("rules"):
        said["techlead"].append(f"Hold every pull request to {facts['rules']}.")
        said["dev"].append(f"Read {facts['rules']} before you write.")
    if facts.get("ci"):
        said["techlead"].append(f"CI is {facts['ci']}: a red check is the Dev's to fix, not a reason to approve around it.")
    if facts.get("demo"):
        said["qa"].append("The demo's launch, pages and seed are declared in theswarm.yaml: film what the feature changed there.")
    personas = [Persona(scope=project, key=key, instructions="\n".join(lines)) for key, lines in said.items() if lines]
    return team_yaml.dump(project, personas)
