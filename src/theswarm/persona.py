"""Swarm PO persona — NLU-powered DM handler for the @swarm-po Mattermost account.

The PO is the single client-facing persona for the SWARM team.
Users interact with @swarm-po to create stories, launch cycles, and get reports.
Internal agents (TL, Dev, QA) post updates to #swarm-team but don't receive user messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from theswarm_common.chat import Intent

log = logging.getLogger(__name__)

KNOWN_ACTIONS = [
    "create_stories",
    "run_cycle",
    "show_status",
    "show_plan",
    "show_report",
    "list_stories",
    "list_repos",
    "ping",
    "help",
]

_HELP_TEXT = """\
📋 **TheSwarm — Autonomous Dev Team**

I'm the Product Owner of an autonomous dev team (PO, TechLead, Dev, QA).
Tell me what you want built and I'll coordinate the team.

**What I understand:**
• `Je veux un dashboard` / `Add Google auth` — I'll generate user stories for approval
• `go` / `start` — launch a cycle on the default repo
• `go on owner/repo` — launch a cycle on a specific repo
• `repos` — list allowed repositories
• `status` — check if a cycle is running
• `plan` / `plan du jour` — show today's plan
• `rapport` / `report` — show the latest daily report
• `backlog` / `issues` — list open stories
• `help` — show this message

**How it works:**
1. You describe what you want → I generate user stories
2. You approve → I create GitHub issues
3. You say "go" → the team implements, reviews, tests, and reports back
"""


# ── Repo extraction ──────────────────────────────────────────────────────

_REPO_PATTERN = re.compile(r"(?:on|sur|repo[:\s])\s*([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)")


def _extract_repo(message: str, allowed_repos: list[str], default_repo: str) -> str:
    """Extract target repo from message. Falls back to default_repo."""
    match = _REPO_PATTERN.search(message)
    if match:
        candidate = match.group(1)
        if candidate in allowed_repos:
            return candidate
        # Try partial match (just repo name without owner)
        for repo in allowed_repos:
            if repo.endswith(f"/{candidate}") or repo == candidate:
                return repo
    return default_repo


async def handle_dm(
    message: str,
    user_id: str,
    chat,
    nlu,
    gateway,
) -> None:
    """Handle an incoming DM directed at Swarm PO."""
    intent: Intent = await nlu.parse_intent(message, "swarm_po", KNOWN_ACTIONS)
    log.info(
        "SwarmPO DM intent: action=%s confidence=%.2f params=%s",
        intent.action, intent.confidence, intent.params,
    )

    if intent.confidence < 0.35 or intent.action == "unknown":
        await chat.post_dm(
            user_id,
            "🤔 Je n'ai pas compris. Décris-moi ce que tu veux construire, ou tape `help`.",
        )
        return

    # Extract target repo from message
    vcs_map = getattr(gateway, "_swarm_po_vcs_map", {})
    default_repo = getattr(gateway, "_swarm_po_default_repo", "")
    repo = _extract_repo(message, list(vcs_map.keys()), default_repo)

    if intent.action == "help":
        await chat.post_dm(user_id, _HELP_TEXT)

    elif intent.action == "create_stories":
        await _handle_create_stories(message, user_id, chat, gateway, repo)

    elif intent.action == "run_cycle":
        await _handle_run_cycle(user_id, chat, gateway, repo)

    elif intent.action == "show_status":
        await _handle_show_status(user_id, chat, gateway)

    elif intent.action == "show_plan":
        await _handle_show_plan(user_id, chat, gateway)

    elif intent.action == "show_report":
        await _handle_show_report(user_id, chat, gateway)

    elif intent.action == "list_stories":
        await _handle_list_stories(user_id, chat, gateway)

    elif intent.action == "list_repos":
        await _handle_list_repos(user_id, chat, gateway)

    elif intent.action == "ping":
        await _handle_ping(user_id, chat)


# ── Intent handlers ────────────────────────────────────────────────────────


async def _handle_create_stories(message: str, user_id: str, chat, gateway, repo: str) -> None:
    """Generate user stories from a feature description and present for approval."""
    await chat.post_dm(user_id, f"🧠 Generating user stories for **{repo}**…")

    stories = await gateway.swarm_po_generate_stories(message)
    if not stories:
        await chat.post_dm(user_id, "❌ Could not generate stories. Try rephrasing your request.")
        return

    # Format stories for display
    lines = ["📋 **Generated User Stories:**\n"]
    for i, story in enumerate(stories, 1):
        lines.append(f"**US-{i:03d}**: {story['title']}")
        if story.get("description"):
            lines.append(f"> {story['description'][:200]}")
        lines.append("")

    # Store pending stories for approval
    pending_id = await gateway.swarm_po_store_pending_stories(user_id, stories)

    # Post with approval buttons
    await chat.post_dm_interactive(
        user_id,
        "\n".join(lines),
        actions=[
            {"id": f"swarm_po_approve:{pending_id}", "name": "Approve", "style": "good"},
            {"id": f"swarm_po_reject:{pending_id}", "name": "Cancel", "style": "danger"},
        ],
    )


async def _handle_run_cycle(user_id: str, chat, gateway, repo: str) -> None:
    """Launch a full SWARM dev cycle on the specified repo."""
    if gateway.swarm_po_is_cycle_running():
        phase = gateway.swarm_po_current_phase()
        await chat.post_dm(
            user_id,
            f"⏳ A cycle is already running (phase: **{phase}**).\nWait for it to finish or check `status`.",
        )
        return

    await chat.post_dm(user_id, f"🚀 Launching dev cycle on **{repo}**… Updates in #swarm-team.")
    asyncio.create_task(gateway.run_swarm_cycle(user_id, repo))


async def _handle_show_status(user_id: str, chat, gateway) -> None:
    """Show whether a cycle is running and its current phase."""
    if gateway.swarm_po_is_cycle_running():
        phase = gateway.swarm_po_current_phase()
        await chat.post_dm(user_id, f"⏳ Cycle en cours — phase: **{phase}**")
    else:
        await chat.post_dm(user_id, "✅ Idle — no cycle running. Say `go` to start one.")


async def _handle_show_plan(user_id: str, chat, gateway) -> None:
    """Fetch and display today's daily plan."""
    plan = await gateway.swarm_po_get_plan()
    if plan:
        await chat.post_dm(user_id, f"📋 **Today's Plan:**\n\n{plan}")
    else:
        await chat.post_dm(user_id, "ℹ️ No plan found for today.")


async def _handle_show_report(user_id: str, chat, gateway) -> None:
    """Fetch and display the latest daily report."""
    report = await gateway.swarm_po_get_report()
    if report:
        await chat.post_dm(user_id, f"📊 **Latest Report:**\n\n{report}")
    else:
        await chat.post_dm(user_id, "ℹ️ No report found yet.")


async def _handle_list_repos(user_id: str, chat, gateway) -> None:
    """List allowed repositories."""
    vcs_map = getattr(gateway, "_swarm_po_vcs_map", {})
    default_repo = getattr(gateway, "_swarm_po_default_repo", "")
    if not vcs_map:
        await chat.post_dm(user_id, "ℹ️ No repositories configured.")
        return
    lines = ["📦 **Allowed Repositories:**\n"]
    for repo in vcs_map:
        default = " _(default)_" if repo == default_repo else ""
        lines.append(f"• `{repo}`{default}")
    await chat.post_dm(user_id, "\n".join(lines))


async def _handle_ping(user_id: str, chat) -> None:
    """Respond with interactive buttons to verify the callback flow works."""
    await chat.post_dm_interactive(
        user_id,
        "🏓 Choose a button:",
        actions=[
            {"id": "swarm_po_ping:ping", "name": "Ping", "style": "default"},
            {"id": "swarm_po_pong:ping", "name": "Pong", "style": "good"},
        ],
    )


async def _handle_list_stories(user_id: str, chat, gateway) -> None:
    """List open GitHub issues for the SWARM project."""
    issues = await gateway.swarm_po_list_issues()
    if not issues:
        await chat.post_dm(user_id, "ℹ️ No open issues.")
        return

    lines = ["📋 **Open Issues:**\n"]
    for issue in issues[:15]:
        labels = ", ".join(l["name"] for l in issue.get("labels", []))
        label_str = f" `{labels}`" if labels else ""
        lines.append(f"• **#{issue['number']}** {issue['title']}{label_str}")

    await chat.post_dm(user_id, "\n".join(lines))
