"""Improvements as PRs (D4): from what DevOps measures, a pull request on the pipeline.

One call reads the measures (`OpsReport.facts["measures"]`) and the
pipeline's own files in a clone of the swarm's repository, and answers a
validated `Improvement`: a title, why, the gain expected, the files to
write — the workflows, the Dockerfile, the compose and ignore files,
never the code (`PIPELINE_PATHS`; anything else is refused and the
proposal dropped). The branch is `devops/<slug>-<date>`, the PR body
carries the measures *before* so the next report can be read against
them; the TechLead reviews it like any other PR and the owner merges —
DevOps never merges. `nothing` is an answer too, kept with its reason.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from theswarm.agents.schemas import Improvement
from theswarm.tools import git as git_tools

log = logging.getLogger(__name__)

PIPELINE_PATHS = (".github/workflows/", ".forgejo/workflows/", ".github/actions/", "Dockerfile", ".dockerignore",
                  "docker-compose.yml", "theswarm.yaml")
PIPELINE_FILES_READ = (".github/workflows/ci.yml", ".github/workflows/cd.yml", ".forgejo/workflows/ci.yml",
                       "Dockerfile", ".dockerignore", "docker-compose.yml", "pyproject.toml")
IMPROVE_TIMEOUT_SECONDS = 600
MAX_FILE_CHARS = 24_000  # of each pipeline file in the prompt
BRANCH_PREFIX = "devops/"

IMPROVE_PROMPT = """You are DevOps on the repository {repo}: you own the pipeline, not the code.

What the last runs of the deploy workflow on main measured:
{measures}

The pipeline's files today:
{files}

Propose ONE change to these files that would make the pipeline measurably faster, cheaper or steadier — a cache that is missing, a step that repeats work, a job that could run in parallel, a timeout or a retry that wastes minutes, an image layer rebuilt every time. Keep it small and reviewable: the smallest diff with a real gain, in files under {allowed} only. Never touch the application's code or tests, never remove a check, never change what deploys or where.

If no change is worth a pull request, answer status "nothing" and say why in `rationale`.

Answer with the schema: `title` (one line, imperative, as a commit subject), `rationale` (what the measures say and what the change does about it), `expected_gain` (what should move, and by how much, in the next measures), and `files` — each file's complete new content (the whole file, not a diff), path relative to the repository root.
"""


def clean_path(path: str) -> str:
    """The path without a leading `./` — never `lstrip("./")`, which eats the dot of `.github`."""
    clean = path.strip()
    while clean.startswith("./"):
        clean = clean[2:]
    return clean


def allowed_path(path: str) -> bool:
    """A path DevOps may write: the pipeline's, inside the repository, never the code."""
    clean = clean_path(path)
    if not clean or clean.startswith("/") or ".." in clean.split("/"):
        return False
    return any(clean == p or (p.endswith("/") and clean.startswith(p)) for p in PIPELINE_PATHS)


_PREFIX_RE = re.compile(r"^\s*[a-z]+(\([^)]*\))?!?:\s*", re.IGNORECASE)


def plain_title(title: str) -> str:
    """The title without a conventional prefix Claude may have added (`ci: …`): the PR adds its own."""
    return _PREFIX_RE.sub("", title or "").strip()


def branch_name(title: str, when: datetime | None = None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-") or "improvement"
    return f"{BRANCH_PREFIX}{slug}-{(when or datetime.now(timezone.utc)).strftime('%Y%m%d')}"


def measures_words(facts: dict | None) -> str:
    """The measures as the prompt and the PR body say them, one job a line."""
    measures = (facts or {}).get("measures") or {}
    lines = []
    for j in measures.get("jobs") or []:
        line = f"- {j['name']}: {j['median_min']:g} min median over {j['runs']} runs, p90 {j['p90_min']:g}"
        if j.get("setup_min"):
            line += f", {j['setup_min']:g} min of it setup wait"
        if j.get("failures"):
            line += f", {j['failures']} failed"
        lines.append(line)
    cycle = measures.get("cycle") or {}
    if cycle:
        lines.append(f"- a cycle on the test bed: ${cycle.get('cost_usd') or 0:.2f} and {cycle.get('duration_min') or 0:g} min median over {cycle.get('runs', 0)} runs")
    return "\n".join(lines) or "- nothing measured yet"


def pipeline_files(clone: str) -> str:
    parts = []
    for rel in PIPELINE_FILES_READ:
        path = Path(clone) / rel
        if path.is_file():
            parts.append(f"--- {rel}\n{path.read_text(errors='replace')[:MAX_FILE_CHARS]}")
    return "\n\n".join(parts) or "(no pipeline file found)"


def workspace_for(repo: str, root: str = "") -> str:
    root = root or os.environ.get("SWARM_DEVOPS_WORKSPACE", "") or os.path.join(os.path.expanduser("~"), ".swarm-workspaces", "devops")
    return os.path.join(root, repo.replace("/", "__"))


def pr_body(outcome: Improvement, facts: dict | None, report_at: datetime | None) -> str:
    when = (report_at or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC").lstrip("0")
    return (f"{outcome.rationale}\n\n**Expected gain**: {outcome.expected_gain or 'not stated'}\n\n"
            f"**Measured before** (the deploy workflow on main, read {when}):\n{measures_words(facts)}\n\n"
            "Opened by the DevOps persona (D4) from what it measures; the TechLead reviews it like any other PR, "
            "the owner merges — DevOps never merges. The next daily report reads the measures after.\n")


async def _open_pr_on(github, branch: str) -> dict | None:
    lister = getattr(github, "get_open_prs", None)
    if lister is None:
        return None
    try:
        return next((p for p in await lister() if p.get("head") == branch), None)
    except Exception:  # noqa: BLE001 — then a new PR, and GitHub says if one exists
        return None


async def propose_improvement(stack: dict, report, claude, github, *, workspace_root: str = "", git=git_tools,
                              now: datetime | None = None) -> dict:
    """Measure → one Claude call → a branch, the files, a PR. The answer is a dict the card shows.

    `status` is `opened` (with `pr`, `url`, `title`), `nothing` (with
    `reason`) or `failed` (with `reason`); nothing here raises.
    """
    from theswarm.agents.devops import self_repo

    repo = self_repo(stack)
    if not repo:
        return {"status": "failed", "reason": "no repository declared in stack.ci"}
    try:
        clone = await git.clone_repo(f"https://github.com/{repo}.git", workspace_for(repo, workspace_root))
        prompt = IMPROVE_PROMPT.format(repo=repo, measures=measures_words(getattr(report, "facts", None)),
                                       files=pipeline_files(clone), allowed=", ".join(PIPELINE_PATHS))
        result = await claude.run(prompt, workdir=clone, timeout=IMPROVE_TIMEOUT_SECONDS,
                                  output_schema=Improvement.model_json_schema())
        structured = getattr(result, "structured", None)
        if not structured:
            return {"status": "failed", "reason": "Claude answered no structured improvement"}
        outcome = Improvement.model_validate(structured)
        outcome = outcome.model_copy(update={"title": plain_title(outcome.title)})
        if outcome.status != "proposed" or not outcome.files:
            return {"status": "nothing", "reason": outcome.rationale or "no change worth a pull request"}
        refused = [f.path for f in outcome.files if not allowed_path(f.path)]
        if refused:
            return {"status": "failed", "reason": f"the proposal touches files outside the pipeline: {', '.join(refused)}"}
        branch = branch_name(outcome.title, now)
        await git.create_branch(clone, branch)
        for f in outcome.files:
            target = Path(clone) / clean_path(f.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content)
        if not await git.commit_all(clone, f"ci: {outcome.title}\n\n{outcome.rationale}\n\nExpected gain: {outcome.expected_gain}"):
            return {"status": "nothing", "reason": "the proposed files are what main already has"}
        await git.push_branch(clone, branch)
        pr = await _open_pr_on(github, branch)  # a second ask the same day lands on the PR already open
        if pr is None:
            pr = await github.create_pr(branch, "main", f"ci(devops): {outcome.title}",
                                        pr_body(outcome, getattr(report, "facts", None), getattr(report, "read_at", None)))
        url = pr.get("html_url") or f"https://github.com/{repo}/pull/{pr.get('number')}"
        log.info("DevOps opened PR #%s: %s", pr.get("number"), outcome.title)
        return {"status": "opened", "pr": pr.get("number"), "url": url, "title": outcome.title,
                "expected_gain": outcome.expected_gain, "branch": branch}
    except Exception as exc:  # noqa: BLE001 — the answer is the record
        log.exception("DevOps: the improvement failed")
        return {"status": "failed", "reason": f"{exc.__class__.__name__}: {str(exc)[:300]}"}
