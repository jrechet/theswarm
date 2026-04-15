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
    "add_repo",
    "remove_repo",
    "set_default",
    "ping",
    "help",
]

_HELP_TEXT = """\
📋 **TheSwarm — Autonomous Dev Team**

I'm the Product Owner of an autonomous dev team (PO, TechLead, Dev, QA).
Tell me what you want built and I'll coordinate the team.

**Repo management:**
• `add owner/repo` — connect a GitHub repository
• `remove owner/repo` — disconnect a repository
• `use owner/repo` / `switch to owner/repo` — set the default repo
• `repos` — list connected repositories

**Development:**
• Describe a feature (e.g. "I want a dashboard") — I'll generate user stories for approval
• `go` — launch a dev cycle on the default repo
• `go on owner/repo` — launch a cycle on a specific repo

**Status & reports:**
• `status` — check if a cycle is running
• `plan` — show today's plan
• `report` — show the latest daily report
• `backlog` / `issues` — list open stories

**How it works:**
1. Add a repo → `add owner/repo`
2. Describe what you want → I generate user stories
3. You approve → I create GitHub issues
4. Say `go` → the team implements, reviews, tests, and reports back
"""


# ── Repo extraction ──────────────────────────────────────────────────────

# Matches GitHub URLs: https://github.com/owner/repo(.git)
_URL_PATTERN = re.compile(r"https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+?)(?:\.git)?(?:\s|$|[)\],])")
# Matches "on owner/repo", "sur owner/repo", "repo: owner/repo"
_PREFIX_PATTERN = re.compile(r"(?:on|sur|repo[:\s])\s*([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)")
# Matches bare owner/repo anywhere in the message
_BARE_PATTERN = re.compile(r"(?:^|\s)([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)(?:\s|$)")


def _extract_repo_from_message(message: str) -> str | None:
    """Extract an owner/repo string from a message (URL, prefix, or bare). Returns None if not found."""
    # Try GitHub URL first
    m = _URL_PATTERN.search(message)
    if m:
        return m.group(1)
    # Try prefix pattern (on/sur/repo:)
    m = _PREFIX_PATTERN.search(message)
    if m:
        return m.group(1)
    # Try bare owner/repo
    m = _BARE_PATTERN.search(message)
    if m:
        return m.group(1)
    return None


def _extract_repo(message: str, allowed_repos: list[str], default_repo: str) -> str:
    """Extract target repo from message, matched against allowed list. Falls back to default_repo."""
    candidate = _extract_repo_from_message(message)
    if not candidate:
        return default_repo
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
        await _handle_show_plan(user_id, chat, gateway, repo)

    elif intent.action == "show_report":
        await _handle_show_report(user_id, chat, gateway, repo)

    elif intent.action == "list_stories":
        await _handle_list_stories(user_id, chat, gateway, repo)

    elif intent.action == "list_repos":
        await _handle_list_repos(user_id, chat, gateway)

    elif intent.action == "add_repo":
        await _handle_add_repo(message, user_id, chat, gateway)

    elif intent.action == "remove_repo":
        await _handle_remove_repo(message, user_id, chat, gateway)

    elif intent.action == "set_default":
        await _handle_set_default(message, user_id, chat, gateway)

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

    # Store pending stories for approval (with target repo)
    pending_id = await gateway.swarm_po_store_pending_stories(user_id, stories, repo)

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


async def _handle_show_plan(user_id: str, chat, gateway, repo: str = "") -> None:
    """Fetch and display today's daily plan."""
    plan = await gateway.swarm_po_get_plan_for_repo(repo)
    if plan:
        await chat.post_dm(user_id, f"📋 **Today's Plan** ({repo}):\n\n{plan}")
    else:
        await chat.post_dm(user_id, f"ℹ️ No plan found for today on `{repo}`.")


async def _handle_show_report(user_id: str, chat, gateway, repo: str = "") -> None:
    """Fetch and display the latest daily report."""
    report = await gateway.swarm_po_get_report_for_repo(repo)
    if report:
        await chat.post_dm(user_id, f"📊 **Latest Report** ({repo}):\n\n{report}")
    else:
        await chat.post_dm(user_id, f"ℹ️ No report found yet for `{repo}`.")


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


async def _handle_list_stories(user_id: str, chat, gateway, repo: str = "") -> None:
    """List open GitHub issues for the specified repo."""
    issues = await gateway.swarm_po_list_issues(repo)
    if not issues:
        await chat.post_dm(user_id, f"ℹ️ No open issues on `{repo}`.")
        return

    lines = [f"📋 **Open Issues** (`{repo}`):\n"]
    for issue in issues[:15]:
        labels = ", ".join(
            (l if isinstance(l, str) else l.get("name", ""))
            for l in issue.get("labels", [])
        )
        label_str = f" `{labels}`" if labels else ""
        lines.append(f"• **#{issue['number']}** {issue['title']}{label_str}")

    await chat.post_dm(user_id, "\n".join(lines))


async def _handle_add_repo(message: str, user_id: str, chat, gateway) -> None:
    """Add a new repository to the bot's allowlist."""
    repo_name = _extract_repo_from_message(message)
    if not repo_name:
        await chat.post_dm(user_id, "❌ Could not parse repo. Use `add owner/repo` or `add https://github.com/owner/repo`.")
        return

    await chat.post_dm(user_id, f"🔗 Connecting to `{repo_name}`…")
    success, msg = await gateway.add_repo(repo_name)
    emoji = "✅" if success else "❌"
    await chat.post_dm(user_id, f"{emoji} {msg}")

    if success:
        # Show updated repo list
        await _handle_list_repos(user_id, chat, gateway)


async def _handle_remove_repo(message: str, user_id: str, chat, gateway) -> None:
    """Remove a repository from the bot's allowlist."""
    repo_name = _extract_repo_from_message(message)
    if not repo_name:
        await chat.post_dm(user_id, "❌ Could not parse repo. Use `remove owner/repo`.")
        return

    success, msg = gateway.remove_repo(repo_name)
    emoji = "✅" if success else "❌"
    await chat.post_dm(user_id, f"{emoji} {msg}")

    if success:
        await _handle_list_repos(user_id, chat, gateway)


async def _handle_set_default(message: str, user_id: str, chat, gateway) -> None:
    """Set the default repository."""
    repo_name = _extract_repo_from_message(message)
    if not repo_name:
        await chat.post_dm(user_id, "❌ Could not parse repo. Use `use owner/repo` or `switch to owner/repo`.")
        return

    # Try exact match first, then partial match against registered repos
    vcs_map = getattr(gateway, "_swarm_po_vcs_map", {})
    if repo_name not in vcs_map:
        for registered in vcs_map:
            if registered.endswith(f"/{repo_name}") or registered == repo_name:
                repo_name = registered
                break

    success, msg = gateway.set_default_repo(repo_name)
    emoji = "✅" if success else "❌"
    await chat.post_dm(user_id, f"{emoji} {msg}")
