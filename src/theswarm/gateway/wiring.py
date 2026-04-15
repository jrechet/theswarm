"""Wire the Swarm PO agent — event handlers for actions and channel commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from theswarm_common.models import AgentEvent

if TYPE_CHECKING:
    from theswarm.gateway.app import SwarmGateway

log = logging.getLogger(__name__)


def wire_swarm_po(gw: SwarmGateway, vcs_map: dict, default_repo: str, chat, team_chat) -> None:
    """Wire the Swarm PO agent into the gateway."""
    swarm_po_config = gw.settings.agents.swarm_po
    gw._swarm_po_chat = chat
    gw._swarm_po_team_chat = team_chat
    gw._swarm_po_vcs_map = vcs_map
    gw._swarm_po_default_repo = default_repo
    gw._swarm_po_github = vcs_map.get(default_repo)
    gw._swarm_po_config = swarm_po_config

    # Set default repo and base URL on dashboard for reports and history
    from theswarm.dashboard import get_dashboard_state
    dash = get_dashboard_state()
    dash.github_repo = default_repo
    ext_url = getattr(gw.settings.server, "external_url", "")
    if ext_url:
        dash.base_url = ext_url.rstrip("/")

    async def on_swarm_po_action(event: AgentEvent):
        action_id = event.payload.get("action_id", "")
        if not action_id.startswith("swarm_po_"):
            return

        parts = action_id.split(":", 1)
        if len(parts) != 2:
            return

        action_type = parts[0]
        pending_id = parts[1]

        # Ping/pong callback — no pending stories needed
        if action_type == "swarm_po_ping":
            user_id = event.payload.get("user_id", "")
            if chat and user_id:
                await chat.post_dm(user_id, "ping")
            return

        if action_type == "swarm_po_pong":
            user_id = event.payload.get("user_id", "")
            if chat and user_id:
                await chat.post_dm(user_id, "pong")
            return

        if action_type == "swarm_po_dismiss":
            return  # silently dismiss

        pending = gw._swarm_po_pending_stories.pop(pending_id, None)
        if not pending:
            log.warning("SwarmPO: no pending stories for id=%s", pending_id)
            return

        user_id = pending["user_id"]
        stories = pending["stories"]
        target_repo = pending.get("repo", "")

        if action_type == "swarm_po_approve":
            from theswarm.gateway.stories import create_issues
            await create_issues(gw, user_id, stories, repo=target_repo)
        else:
            if chat:
                await chat.post_dm(user_id, "🗑️ Stories cancelled.")

    gw.register("chat_action", on_swarm_po_action)

    async def on_swarm_po_chat(event: AgentEvent):
        msg = event.payload.get("message", "").strip()
        msg_lower = msg.lower()
        if not (msg_lower.startswith("!swarm-po") or msg_lower.startswith("/swarm-po")):
            return

        channel_id = event.payload.get("channel_id", "")
        cmd = msg_lower.split(None, 1)[1] if " " in msg_lower else ""

        if cmd in ("status", ""):
            running = gw._swarm_po_cycle_running
            phase = gw._swarm_po_current_phase
            if running:
                text = f"⏳ Cycle en cours — phase: **{phase}**"
            else:
                text = "✅ Idle — no cycle running."
            if chat:
                await chat.post_message_to_channel(channel_id, text)
        elif cmd in ("plan", "plan du jour"):
            plan = await gw.swarm_po_get_plan()
            text = f"📋 **Today's Plan:**\n\n{plan}" if plan else "ℹ️ No plan found."
            if chat:
                await chat.post_message_to_channel(channel_id, text)
        elif cmd in ("report", "rapport"):
            report = await gw.swarm_po_get_report()
            text = f"📊 **Latest Report:**\n\n{report}" if report else "ℹ️ No report found."
            if chat:
                await chat.post_message_to_channel(channel_id, text)

    gw.register("chat_message", on_swarm_po_chat)
    log.info("Swarm PO agent wired into gateway (repos=%s, default=%s)",
             list(vcs_map.keys()), default_repo)
