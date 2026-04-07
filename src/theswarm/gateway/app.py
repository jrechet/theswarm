"""SwarmGateway core — FastAPI app, event bus, health endpoint, server start."""

from __future__ import annotations

import logging
import secrets
from collections import defaultdict

import uvicorn
from fastapi import FastAPI

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

        # Callback verification token — embedded in Mattermost button context,
        # checked on every callback to reject forged requests.
        self.callback_token: str = secrets.token_urlsafe(32)

        # Dashboard
        from theswarm.dashboard import register_dashboard_routes
        register_dashboard_routes(self.app)

        # Headless API (allowed repos wired later via wire_swarm_po)
        from theswarm.api import register_api_routes
        allowed = getattr(settings, "_api_allowed_repos", [])
        register_api_routes(self.app, allowed_repos=allowed)

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
            has_github = bool(getattr(self, "_swarm_po_github", None))
            has_chat = bool(self._swarm_po_chat)
            overall = "ok" if (has_github and has_chat) else "degraded"
            return {
                "status": overall,
                "service": "theswarm",
                "bots": {"swarm_po": swarm_po_status},
                "repos": list(vcs_map.keys()),
                "default_repo": getattr(self, "_swarm_po_default_repo", ""),
                "checks": {
                    "github": "connected" if has_github else "missing",
                    "chat": "connected" if has_chat else "missing",
                },
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

    def swarm_po_is_cycle_running(self) -> bool:
        return self._swarm_po_cycle_running

    def swarm_po_current_phase(self) -> str:
        return self._swarm_po_current_phase or "unknown"

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

    # --- Delegated methods (kept on class for backward compat with persona.py) ---

    def wire_swarm_po(self, vcs_map: dict, default_repo: str, chat, team_chat) -> None:
        from theswarm.gateway.wiring import wire_swarm_po
        wire_swarm_po(self, vcs_map, default_repo, chat, team_chat)

    async def swarm_po_generate_stories(self, description: str) -> list[dict]:
        from theswarm.gateway.stories import generate_stories
        return await generate_stories(self, description)

    async def swarm_po_store_pending_stories(self, user_id: str, stories: list[dict]) -> str:
        from theswarm.gateway.stories import store_pending_stories
        return await store_pending_stories(self, user_id, stories)

    async def run_swarm_cycle(self, user_id: str, repo_name: str = "") -> None:
        from theswarm.gateway.cycle_runner import run_swarm_cycle
        await run_swarm_cycle(self, user_id, repo_name)

    async def swarm_po_get_plan(self) -> str | None:
        from theswarm.gateway.queries import get_plan
        return await get_plan(self)

    async def swarm_po_get_report(self) -> str | None:
        from theswarm.gateway.queries import get_report
        return await get_report(self)

    async def swarm_po_list_issues(self) -> list[dict]:
        from theswarm.gateway.queries import list_issues
        return await list_issues(self)
