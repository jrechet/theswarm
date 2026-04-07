"""Cycle orchestration — run a SWARM dev cycle with progress updates and retries."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theswarm.gateway.app import SwarmGateway

log = logging.getLogger(__name__)


async def run_swarm_cycle(gw: SwarmGateway, user_id: str, repo_name: str = "") -> None:
    """Run a full SWARM dev cycle with progress updates to Mattermost."""
    from theswarm.cycle import run_daily_cycle
    from theswarm.config import CycleConfig

    chat = gw._swarm_po_chat
    team_chat = gw._swarm_po_team_chat
    config = gw._swarm_po_config

    github_repo = repo_name or gw._swarm_po_default_repo
    if not github_repo:
        if chat:
            await chat.post_dm(user_id, "❌ No repo specified and no `default_repo` configured.")
        return
    vcs_map = getattr(gw, "_swarm_po_vcs_map", {})
    if github_repo not in vcs_map:
        if chat:
            allowed = ", ".join(vcs_map.keys()) or "none"
            await chat.post_dm(user_id, f"❌ Repo `{github_repo}` not in allowed list: {allowed}")
        return

    gw._swarm_po_cycle_running = True
    gw._swarm_po_current_phase = "starting"

    # Dashboard state
    from theswarm.dashboard import get_dashboard_state
    dash = get_dashboard_state()
    dash.start_cycle(github_repo)

    # Thread-per-cycle: first message creates the thread root
    cycle_thread_id = ""

    async def on_progress(role: str, message: str) -> None:
        nonlocal cycle_thread_id
        gw._swarm_po_current_phase = f"{role}: {message[:50]}"
        dash.current_phase = f"{role}: {message[:50]}"
        dash.push_event(role, message)
        if team_chat:
            try:
                team_channel = config.team_channel if config else "swarm-team"
                post_id = await team_chat.post_message(
                    team_channel,
                    f"[**{role}**] {message}",
                    root_id=cycle_thread_id,
                )
                if not cycle_thread_id and post_id:
                    cycle_thread_id = post_id
            except Exception:
                log.warning("SwarmPO: failed to post progress to team channel")

    max_retries = 2
    try:
        for attempt in range(1, max_retries + 1):
            try:
                cycle_config = CycleConfig(github_repo=github_repo)
                result = await run_daily_cycle(cycle_config, on_progress=on_progress)

                dash.cost_so_far = result.get("cost_usd", 0.0)

                # Store report for serving at /swarm/reports/{date}
                cycle_date = result.get("date", "")
                if cycle_date:
                    dash.store_report(cycle_date, result)

                if chat:
                    cost = result.get("cost_usd", 0)
                    prs = result.get("prs", [])
                    merged = sum(1 for r in result.get("reviews", []) if r.get("decision") == "APPROVE")
                    summary = f"🏁 **Cycle terminé !**\n"
                    summary += f"PRs: {len(prs)} opened, {merged} merged | Cost: ${cost:.2f}\n"
                    # Include report link if base_url is configured
                    if dash.base_url and cycle_date:
                        report_url = f"{dash.base_url}/reports/{cycle_date}"
                        summary += f"\n📊 [Voir le rapport]({report_url})"
                    else:
                        report = result.get("daily_report", "")
                        if report:
                            summary += f"\n{report}"
                    await chat.post_dm(user_id, summary)
                return

            except Exception as e:
                error_type = type(e).__name__
                phase = gw._swarm_po_current_phase
                log.exception("SwarmPO: cycle failed (attempt %d/%d) at phase '%s'",
                              attempt, max_retries, phase)

                is_transient = any(k in str(e).lower() for k in [
                    "rate limit", "timeout", "connection", "503", "502",
                ])
                if is_transient and attempt < max_retries:
                    retry_msg = f"⚠️ Erreur transitoire ({error_type}) pendant **{phase}**. Retry {attempt}/{max_retries}…"
                    if chat:
                        await chat.post_dm(user_id, retry_msg)
                    if team_chat:
                        team_channel = config.team_channel if config else "swarm-team"
                        await team_chat.post_message(team_channel, f"[**System**] {retry_msg}")
                    await asyncio.sleep(10)
                    continue

                if chat:
                    await chat.post_dm(
                        user_id,
                        f"❌ **Cycle échoué** pendant **{phase}**\n\n"
                        f"Erreur: `{error_type}: {e}`\n\n"
                        f"Le cycle peut être relancé avec `go`.",
                    )
                if team_chat:
                    team_channel = config.team_channel if config else "swarm-team"
                    await team_chat.post_message(
                        team_channel,
                        f"[**System**] ❌ Cycle failed at **{phase}**: `{error_type}: {e}`",
                    )
                return
    finally:
        gw._swarm_po_cycle_running = False
        gw._swarm_po_current_phase = ""
        dash.end_cycle()
