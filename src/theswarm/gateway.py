"""TheSwarm Gateway — DM handling, approval flow, cycle execution."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import starlette.requests

from theswarm_common.models import AgentEvent

log = logging.getLogger(__name__)


class SwarmGateway:
    """Gateway for the SWARM MVP autonomous dev team.

    Handles:
    - @swarm-po DM routing (via NLU intent classification)
    - Story approval/rejection button callbacks
    - Dev cycle execution with progress updates
    - Plan/report/status queries
    """

    def __init__(self, settings) -> None:
        self.settings = settings
        self.app = FastAPI(title="TheSwarm")
        self._handlers: dict[str, list] = defaultdict(list)

        # Swarm PO state
        self._swarm_po_chat = None
        self._swarm_po_team_chat = None
        self._swarm_po_github = None
        self._swarm_po_config = None
        self._swarm_po_pending_stories: dict[str, dict] = {}
        self._swarm_po_cycle_running = False
        self._swarm_po_current_phase = ""

        # NLU
        self._nlu = None

        # Health endpoint
        @self.app.get("/health")
        async def health():
            swarm_po_status = "disabled"
            if self._swarm_po_chat:
                swarm_po_status = "running"
                if self._swarm_po_cycle_running:
                    swarm_po_status = f"running (phase: {self._swarm_po_current_phase})"
            vcs_map = getattr(self, "_swarm_po_vcs_map", {})
            return {
                "status": "ok",
                "service": "theswarm",
                "bots": {"swarm_po": swarm_po_status},
                "repos": list(vcs_map.keys()),
                "default_repo": getattr(self, "_swarm_po_default_repo", ""),
            }

    def register(self, event_type: str, handler) -> None:
        self._handlers[event_type].append(handler)

    async def route_event(self, event: AgentEvent) -> None:
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                log.exception("Error in handler for event_type=%s", event.event_type)

    async def route_dm_event(self, bot_name: str, message: str, user_id: str) -> None:
        """Route a DM to the swarm_po persona."""
        if bot_name != "swarm_po":
            return

        from theswarm.persona import handle_dm

        chat = self._swarm_po_chat
        nlu = self._nlu
        if not chat or not nlu:
            log.warning("SwarmPO DM received but chat or NLU not configured")
            return

        try:
            await handle_dm(message, user_id, chat, nlu, self)
        except Exception:
            log.exception("Error handling swarm_po DM")

    def wire_swarm_po(self, vcs_map: dict, default_repo: str, chat, team_chat) -> None:
        """Wire the Swarm PO agent into the gateway."""
        swarm_po_config = self.settings.agents.swarm_po
        self._swarm_po_chat = chat
        self._swarm_po_team_chat = team_chat
        self._swarm_po_vcs_map = vcs_map  # repo_name -> PyGithub Repository
        self._swarm_po_default_repo = default_repo
        self._swarm_po_github = vcs_map.get(default_repo)  # backward compat
        self._swarm_po_config = swarm_po_config

        # Handle approval/rejection button clicks
        async def on_swarm_po_action(event: AgentEvent):
            action_id = event.payload.get("action_id", "")
            if not action_id.startswith("swarm_po_"):
                return

            parts = action_id.split(":", 1)
            if len(parts) != 2:
                return

            action_type = parts[0]  # swarm_po_approve or swarm_po_reject
            pending_id = parts[1]

            pending = self._swarm_po_pending_stories.pop(pending_id, None)
            if not pending:
                log.warning("SwarmPO: no pending stories for id=%s", pending_id)
                return

            user_id = pending["user_id"]
            stories = pending["stories"]

            if action_type == "swarm_po_approve":
                await self._swarm_po_create_issues(user_id, stories)
            else:
                if chat:
                    await chat.post_dm(user_id, "🗑️ Stories cancelled.")

        self.register("chat_action", on_swarm_po_action)

        # Handle !swarm-po / /swarm-po channel commands
        async def on_swarm_po_chat(event: AgentEvent):
            msg = event.payload.get("message", "").strip()
            msg_lower = msg.lower()
            if not (msg_lower.startswith("!swarm-po") or msg_lower.startswith("/swarm-po")):
                return

            channel_id = event.payload.get("channel_id", "")
            cmd = msg_lower.split(None, 1)[1] if " " in msg_lower else ""

            if cmd in ("status", ""):
                running = self._swarm_po_cycle_running
                phase = self._swarm_po_current_phase
                if running:
                    text = f"⏳ Cycle en cours — phase: **{phase}**"
                else:
                    text = "✅ Idle — no cycle running."
                if chat:
                    await chat.post_message_to_channel(channel_id, text)
            elif cmd in ("plan", "plan du jour"):
                plan = await self.swarm_po_get_plan()
                text = f"📋 **Today's Plan:**\n\n{plan}" if plan else "ℹ️ No plan found."
                if chat:
                    await chat.post_message_to_channel(channel_id, text)
            elif cmd in ("report", "rapport"):
                report = await self.swarm_po_get_report()
                text = f"📊 **Latest Report:**\n\n{report}" if report else "ℹ️ No report found."
                if chat:
                    await chat.post_message_to_channel(channel_id, text)

        self.register("chat_message", on_swarm_po_chat)
        log.info("Swarm PO agent wired into gateway (repos=%s, default=%s)",
                 list(vcs_map.keys()), default_repo)

    async def swarm_po_generate_stories(self, description: str) -> list[dict]:
        """Call Claude CLI to generate user stories from a feature description."""
        from theswarm.tools.claude import ClaudeCLI

        prompt = f"""\
You are a Product Owner. Generate user stories from this feature request.

Feature request: {description}

Return a JSON array of user stories:
[
    {{
        "title": "US: Short imperative title",
        "description": "As a [user], I want [goal] so that [benefit].\\n\\nAcceptance criteria:\\n- [ ] ..."
    }}
]

Rules:
- 2-5 stories, ordered by priority
- Each story must be independently implementable
- Include acceptance criteria
- Return ONLY the JSON array, no markdown fences.
"""
        try:
            cli = ClaudeCLI(model="sonnet")
            result = await cli.run(prompt, timeout=60)

            # Parse JSON from response
            import re
            text = result.text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```\w*\n", "", text)
                text = re.sub(r"\n```\s*$", "", text)

            stories = json.loads(text)
            if isinstance(stories, list):
                return stories
            if isinstance(stories, dict):
                return stories.get("stories", [])
        except Exception:
            log.exception("SwarmPO: failed to generate stories")
        return []

    async def swarm_po_store_pending_stories(self, user_id: str, stories: list[dict]) -> str:
        """Store stories pending approval, return a unique ID."""
        pending_id = uuid.uuid4().hex[:8]
        self._swarm_po_pending_stories[pending_id] = {
            "user_id": user_id,
            "stories": stories,
        }
        return pending_id

    async def _swarm_po_create_issues(self, user_id: str, stories: list[dict]) -> None:
        """Create GitHub issues from approved stories."""
        vcs = self._swarm_po_github
        chat = self._swarm_po_chat

        if not vcs:
            if chat:
                await chat.post_dm(user_id, "❌ GitHub not configured for SWARM PO.")
            return

        created = []
        loop = asyncio.get_running_loop()
        for story in stories:
            try:
                issue = await loop.run_in_executor(
                    None,
                    lambda s=story: vcs.create_issue(
                        title=s["title"],
                        body=s.get("description", ""),
                        labels=["status:backlog"],
                    ),
                )
                created.append(f"#{issue.number}")
            except Exception as e:
                log.error("SwarmPO: failed to create issue: %s", e)

        if chat:
            if created:
                await chat.post_dm(
                    user_id,
                    f"✅ Created **{len(created)}** issues: {', '.join(created)}\n\nSay `go` to launch the dev cycle!",
                )
            else:
                await chat.post_dm(user_id, "❌ Failed to create issues.")

    def swarm_po_is_cycle_running(self) -> bool:
        return self._swarm_po_cycle_running

    def swarm_po_current_phase(self) -> str:
        return self._swarm_po_current_phase or "unknown"

    async def run_swarm_cycle(self, user_id: str, repo_name: str = "") -> None:
        """Run a full SWARM dev cycle with progress updates to Mattermost."""
        from theswarm.cycle import run_daily_cycle
        from theswarm.config import CycleConfig

        chat = self._swarm_po_chat
        team_chat = self._swarm_po_team_chat
        config = self._swarm_po_config

        github_repo = repo_name or self._swarm_po_default_repo
        if not github_repo:
            if chat:
                await chat.post_dm(user_id, "❌ No repo specified and no `default_repo` configured.")
            return
        vcs_map = getattr(self, "_swarm_po_vcs_map", {})
        if github_repo not in vcs_map:
            if chat:
                allowed = ", ".join(vcs_map.keys()) or "none"
                await chat.post_dm(user_id, f"❌ Repo `{github_repo}` not in allowed list: {allowed}")
            return

        self._swarm_po_cycle_running = True
        self._swarm_po_current_phase = "starting"

        async def on_progress(role: str, message: str) -> None:
            self._swarm_po_current_phase = f"{role}: {message[:50]}"
            if team_chat:
                try:
                    team_channel = config.team_channel if config else "swarm-team"
                    await team_chat.post_message(team_channel, f"[**{role}**] {message}")
                except Exception:
                    log.warning("SwarmPO: failed to post progress to team channel")

        max_retries = 2
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    cycle_config = CycleConfig(github_repo=github_repo)
                    result = await run_daily_cycle(cycle_config, on_progress=on_progress)

                    # Success — send report to user
                    if chat:
                        report = result.get("daily_report", "")
                        cost = result.get("cost_usd", 0)
                        prs = result.get("prs", [])
                        summary = f"✅ **Cycle terminé !**\n"
                        summary += f"PRs: {len(prs)} | Cost: ${cost:.2f}\n"
                        if report:
                            summary += f"\n{report}"
                        else:
                            summary += "\n(no daily report generated)"
                        await chat.post_dm(user_id, summary)
                    return  # success, exit

                except Exception as e:
                    error_type = type(e).__name__
                    phase = self._swarm_po_current_phase
                    log.exception("SwarmPO: cycle failed (attempt %d/%d) at phase '%s'",
                                  attempt, max_retries, phase)

                    # Retry on transient errors
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

                    # Non-transient or last attempt — report failure
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
                    return  # give up
        finally:
            self._swarm_po_cycle_running = False
            self._swarm_po_current_phase = ""

    async def swarm_po_get_plan(self) -> str | None:
        """Fetch today's daily plan from the target repo."""
        vcs = self._swarm_po_github
        if not vcs:
            return None
        try:
            from datetime import date
            path = f"docs/daily-plans/{date.today().isoformat()}.md"
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
        except Exception:
            return None

    async def swarm_po_get_report(self) -> str | None:
        """Fetch the latest daily report from the target repo."""
        vcs = self._swarm_po_github
        if not vcs:
            return None
        try:
            from datetime import date
            path = f"docs/daily-reports/{date.today().isoformat()}.md"
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: vcs.get_file_content(path))
        except Exception:
            return None

    async def swarm_po_list_issues(self) -> list[dict]:
        """List open issues for the SWARM target repo."""
        vcs = self._swarm_po_github
        if not vcs:
            return []
        try:
            loop = asyncio.get_running_loop()
            issues = await loop.run_in_executor(None, lambda: vcs.list_issues(state="open"))
            return [{"number": i.number, "title": i.title, "labels": [{"name": l} for l in i.labels]} for i in issues]
        except Exception:
            log.exception("SwarmPO: failed to list issues")
            return []

    async def start(self) -> None:
        """Start the FastAPI server."""
        log.info("Swarm Gateway starting...")
        log.info("Registered event types: %s", list(self._handlers.keys()))

        config = uvicorn.Config(
            self.app,
            host=self.settings.server.host,
            port=self.settings.server.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()
