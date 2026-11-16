"""What the MCP server offers (phase B, B5 — read and pilot).

Each tool takes the app's `state` and its arguments, and answers a plain
dict. Reading is free. Piloting does what the owner does on the pages, by
the same doors: `start_feature` is the composer's "Create and play",
`say_to_cycle` the theater's field, `pause_cycle` its Pause. A team is never changed from here: `propose_team` keeps a team file for
the owner, who accepts or refuses it on Settings → Agents.
"""

from __future__ import annotations

import logging
import os

from theswarm.presentation.web.mcp.protocol import Tool, ToolError

log = logging.getLogger(__name__)

FEED_LINES = 15
_REPO = {"type": "string", "description": "A registered project, as owner/name"}
_CYCLE = {"type": "string", "description": "A cycle id (12 hex characters), from start_feature or list_cycles"}


async def _project_names(state) -> list[str]:
    repo = getattr(state, "project_repo", None)
    if repo is None:
        return []
    return sorted({str(p.repo) for p in await repo.list_all() if "/" in str(p.repo)})


async def _known_project(state, name: str) -> str:
    if name not in await _project_names(state):
        raise ToolError(f"{name!r} is not a registered project — list_projects names them")
    return name


def _base_url(state) -> str:
    # EXTERNAL_URL is the host; the app lives under its base path (`/swarm` on prod).
    # The first link the MCP handed out on prod (2026-11-16) lacked it and answered 404.
    external = (os.environ.get("EXTERNAL_URL") or "").rstrip("/")
    return f"{external}{getattr(state, 'base_path', '')}"


def _live(record) -> dict:
    return {
        "cycle_id": record.id, "project": record.repo, "issue_number": record.issue_number,
        "status": record.status.value, "started_at": record.started_at or record.created_at,
        "completed_at": record.completed_at or None, "waiting_for": getattr(record, "waiting", "") or None,
        "spent_usd": round(float(getattr(record, "spent_usd", 0.0) or 0.0), 2) or None,
        "error": record.error,
    }


async def list_projects(state, arguments: dict) -> dict:
    from theswarm.api import get_cycle_tracker
    from theswarm.cycle_gate import max_concurrent_cycles, repo_max_cycles

    running: dict[str, int] = {}
    for record in get_cycle_tracker().list_recent(limit=200):
        if record.status.value in ("running", "queued"):
            running[record.repo] = running.get(record.repo, 0) + 1
    return {
        "cycles_at_once_in_all": max_concurrent_cycles(),
        "projects": [{"project": name, "cycles_at_once": repo_max_cycles(name), "live_cycles": running.get(name, 0)}
                     for name in await _project_names(state)],
    }


async def list_cycles(state, arguments: dict) -> dict:
    from theswarm.api import get_cycle_tracker

    project = arguments.get("project") or ""
    limit = max(1, min(int(arguments.get("limit") or 10), 50))
    seen: dict[str, dict] = {}
    for record in get_cycle_tracker().list_recent(limit=200):
        if not project or record.repo == project:
            seen[record.id] = _live(record)
    cycle_repo = getattr(state, "cycle_repo", None)
    if cycle_repo is not None:
        rows = await (cycle_repo.list_by_project(project, limit=limit) if project else cycle_repo.list_recent(limit=limit))
        for row in rows:
            seen.setdefault(str(row.id), {
                "cycle_id": str(row.id), "project": row.project_id, "issue_number": getattr(row, "issue_number", None),
                "status": row.status.value, "started_at": row.started_at.isoformat() if row.started_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None, "waiting_for": None,
                "spent_usd": round(row.total_cost_usd, 2) or None, "error": getattr(row, "error", "") or None,
            })
    ordered = sorted(seen.values(), key=lambda c: str(c.get("started_at") or ""), reverse=True)
    return {"cycles": ordered[:limit]}


async def get_cycle(state, arguments: dict) -> dict:
    from theswarm.api import get_cycle_tracker
    from theswarm.application.services.progress_bridge import get_phase_history

    cycle_id = str(arguments["cycle_id"])
    record = get_cycle_tracker().get(cycle_id)
    row = None
    query = getattr(state, "get_cycle_status_query", None)
    if query is not None:
        row = await query.execute(cycle_id)
    if record is None and row is None:
        raise ToolError(f"No cycle {cycle_id!r} — list_cycles names them")
    if record is not None:
        answer = _live(record)
    else:
        answer = {"cycle_id": row.id, "project": row.project_id, "issue_number": row.issue_number,
                  "status": row.status, "started_at": row.started_at, "completed_at": row.completed_at,
                  "waiting_for": None, "spent_usd": round(row.total_cost_usd, 2) or None, "error": row.error or None}
    history = get_phase_history(cycle_id)
    answer["phase"] = history[-1]["phase"] if history else (row.phases[-1].phase if row and row.phases else None)
    if row is not None:
        answer["pull_requests_opened"], answer["pull_requests_merged"] = row.prs_opened, row.prs_merged
        answer["continued_as"] = row.resumed_as or None
        if not answer.get("spent_usd") and row.total_cost_usd:
            answer["spent_usd"] = round(row.total_cost_usd, 2)
    feed = []
    thoughts = getattr(state, "get_agent_thoughts_query", None)
    if thoughts is not None:
        entries = await thoughts.execute(cycle_id, include_activity=True)
        feed = [{"at": e.occurred_at.strftime("%H:%M:%S"), "who": e.agent, "said": e.text[:300]}
                for e in entries[-FEED_LINES:] if e.text]
    answer["last_said"] = feed
    answer["theater"] = f"{_base_url(state)}/cycles/{cycle_id}"
    return answer


async def get_team(state, arguments: dict) -> dict:
    service = getattr(state, "personas", None)
    if service is None:
        raise ToolError("Teams need the database")
    project = arguments.get("project") or ""
    if project:
        await _known_project(state, project)
    await service.refresh()
    team = service.team(project)
    from theswarm.domain.agents.roles import CYCLE_ROLE_KEYS

    return {
        "team_of": project or "every project (the instance's default)",
        "roles": [{"role": key, "name": team[key].name, "description": team[key].description or None,
                   "instructions": team[key].instructions or None,
                   "model": team[key].model or "the instance's default", "effort": team[key].effort or "Claude Code's default"}
                  for key in CYCLE_ROLE_KEYS],
        "extra_personas": [{"name": e.name, "where": e.point, "effect": e.effect, "looks_for": e.prompt}
                           for e in service.extras_for(project)],
        "team_yaml": service.export_yaml(project),
        "note": "The YAML holds only what the owner wrote for this scope; a role or a field left out inherits.",
    }


async def validate_team_yaml(state, arguments: dict) -> dict:
    from theswarm.application.services import team_yaml

    project = arguments.get("project") or ""
    if project:
        await _known_project(state, project)
    try:
        personas = team_yaml.load(str(arguments["yaml"]), project)
    except team_yaml.TeamYamlError as exc:
        return {"valid": False, "problem": str(exc)}
    return {"valid": True, "roles_written": [p.key for p in personas],
            "note": "Valid. Nothing was changed: the owner imports a team in Settings → Agents."}


async def propose_team(state, arguments: dict) -> dict:
    """A team file kept for the owner to accept or refuse: nothing applies before that."""
    from theswarm.application.services import team_yaml

    service = getattr(state, "personas", None)
    if service is None:
        raise ToolError("Teams need the database")
    project = arguments.get("project") or ""
    if project:
        await _known_project(state, project)
    try:
        proposal_id = await service.propose(project, str(arguments["yaml"]), why=str(arguments.get("why") or ""))
    except team_yaml.TeamYamlError as exc:
        raise ToolError(f"Not proposed: {exc}") from exc
    return {"proposal": proposal_id, "team_of": project or "every project", "status": "waiting for the owner",
            "where": f"{_base_url(state)}/settings/agents" + (f"?team={project}" if project else "") + "#proposals",
            "note": "Nothing was changed. The owner accepts or refuses it in Settings → Agents."}


async def start_feature(state, arguments: dict) -> dict:
    """The composer's "Create and play", or Play on an issue that exists."""
    from theswarm.presentation.web.routes.common import start_targeted_cycle
    from theswarm.tools.github import GitHubClient

    project = await _known_project(state, str(arguments["project"]))
    number, title = arguments.get("issue_number"), str(arguments.get("title") or "").strip()
    if bool(number) == bool(title):
        raise ToolError("start_feature takes either a title (a new feature) or an issue_number (an existing one)")
    if not number:
        if len(title) > 120:
            raise ToolError("A title of 120 characters at most; the detail goes in description")
        created = await GitHubClient(project).create_issue(
            title=title, body=str(arguments.get("description") or "").strip(), labels=["status:backlog"],
        )
        number = int(created["number"])
    flow = str(arguments.get("flow") or "")
    if flow:
        from theswarm.domain.teams.templates import TEMPLATE_KEYS
        from theswarm.presentation.web.routes.common import set_flow

        if flow not in TEMPLATE_KEYS:
            raise ToolError(f"flow is one of {', '.join(TEMPLATE_KEYS)}")
        await set_flow(project, int(number), flow)
    owner, name = project.split("/", 1)
    record = await start_targeted_cycle(state, owner, name, int(number), f"Play on issue #{number}")
    log.info("MCP: feature #%s started on %s → cycle %s", number, project, record.id)
    return {"cycle_id": record.id, "project": project, "issue_number": int(number), "status": record.status.value,
            "theater": f"{_base_url(state)}/cycles/{record.id}",
            "note": "A cycle takes tens of minutes. Read get_cycle now and then; say_to_cycle reaches the working agent."}


def _running(cycle_id: str):
    from theswarm.api import get_cycle_tracker

    record = get_cycle_tracker().get(cycle_id)
    if record is None or record.status.value not in ("running", "queued"):
        raise ToolError(f"Cycle {cycle_id!r} is not running — nobody is there to read or to pause")
    return record


async def say_to_cycle(state, arguments: dict) -> dict:
    from theswarm.application.services.cycle_inbox import InboxError

    inbox = getattr(state, "cycle_inbox", None)
    if inbox is None:
        raise ToolError("Talking to a cycle needs the database")
    record = _running(str(arguments["cycle_id"]))
    stop = bool(arguments.get("stop"))
    try:
        await inbox.post(record.id, str(arguments["message"]), urgent=stop, author="mcp", project_id=record.repo)
    except InboxError as exc:
        raise ToolError(str(exc)) from exc
    return {"sent": True, "cycle_id": record.id,
            "note": ("The running call is cut and goes on with the message." if stop
                     else "The working agent reads it at its next step; nothing is interrupted.")}


async def pause_cycle(state, arguments: dict) -> dict:
    from theswarm.api import get_cycle_tracker

    record = _running(str(arguments["cycle_id"]))
    if not get_cycle_tracker().pause(record.id):
        raise ToolError("Only a running cycle can be paused; this one is still waiting its turn")
    return {"pausing": True, "cycle_id": record.id,
            "note": "It stops at the end of the phase it is in. The owner resumes it from its theater."}


TOOLS: dict[str, Tool] = {tool.name: tool for tool in (
    Tool("list_projects", "The registered projects, how many cycles each may run at once, and how many run now.",
         list_projects),
    Tool("list_cycles", "The latest cycles, running first to finished, optionally of one project.", list_cycles,
         {"project": _REPO, "limit": {"type": "integer", "description": "How many (10 by default, 50 at most)"}}),
    Tool("get_cycle", "One cycle: its status, the phase it is in, what it waits for, what it has spent, its pull "
                      "requests, and the last lines its agents said.", get_cycle, {"cycle_id": _CYCLE}, ("cycle_id",)),
    Tool("get_team", "The team of a project (or the instance's default when no project is given): each role's "
                     "name, description, instructions, model and effort, and the team as YAML.", get_team,
         {"project": _REPO}),
    Tool("validate_team_yaml", "Check a team file without changing anything; says what is wrong when it is.",
         validate_team_yaml, {"yaml": {"type": "string", "description": "The team file's text"}, "project": _REPO},
         ("yaml",)),
    Tool("propose_team", "Propose a team for a project (or for every project): a team file and why. Nothing "
                         "applies until the owner accepts it in Settings → Agents. Read get_team first and send "
                         "the whole file: an accepted proposal replaces what is written for that team.",
         propose_team, {"yaml": {"type": "string", "description": "The whole team file (format: 1)"},
                        "why": {"type": "string", "description": "Why this team, in a sentence or two"},
                        "project": _REPO}, ("yaml",), writes=True),
    Tool("start_feature", "Start a cycle that builds one feature on a project: give a title (and a description) "
                          "to create its issue, or the issue_number of an existing one. Spends the owner's Claude "
                          "window and opens pull requests on the project.", start_feature,
         {"project": _REPO, "title": {"type": "string", "description": "The feature in a few words (a new issue)"},
          "description": {"type": "string", "description": "What it must do, precisely: routes, answers, errors"},
          "issue_number": {"type": "integer", "description": "An existing issue to build instead of a new one"},
          "flow": {"type": "string", "description": "feature (break down, build, review, film — the default), fix "
                                                     "(one task, no breakdown) or review (only review and merge "
                                                     "this feature's open pull requests)"}},
         ("project",), writes=True),
    Tool("say_to_cycle", "Tell a running cycle something: a correction, a detail. The working agent reads it at "
                         "its next step; with stop=true the running call is cut and goes on with the message.",
         say_to_cycle, {"cycle_id": _CYCLE, "message": {"type": "string", "description": "What to tell the agent"},
                        "stop": {"type": "boolean", "description": "Cut the running call instead of waiting"}},
         ("cycle_id", "message"), writes=True),
    Tool("pause_cycle", "Pause a running cycle at the end of the phase it is in; the owner resumes it.", pause_cycle,
         {"cycle_id": _CYCLE}, ("cycle_id",), writes=True),
)}
