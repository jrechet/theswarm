"""Unified server startup: v2 web app + Mattermost + GitHub + legacy gateway.

This replaces the old theswarm/main.py. It starts the v2 FastAPI web dashboard
and wires in the original Mattermost/GitHub/persona integration on top.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets

import uvicorn
from fastapi.responses import JSONResponse

from theswarm.application.events.bus import EventBus
from theswarm.application.services.startup_validator import StartupValidator
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app

log = logging.getLogger(__name__)


# ── Seq structured logging (CLEF over HTTP) ──────────────────────────

def _setup_seq_logging() -> None:
    """Configure Seq log shipping if SEQ_URL is set."""
    seq_url = os.getenv("SEQ_URL", "")
    seq_api_key = os.getenv("SEQ_API_KEY", "")
    if not seq_url:
        return

    import datetime
    import threading
    import urllib.request

    class _SeqCLEFHandler(logging.Handler):
        _LEVEL_MAP = {"DEBUG": "Debug", "INFO": "Information",
                      "WARNING": "Warning", "ERROR": "Error", "CRITICAL": "Fatal"}

        def __init__(self, server_url: str, api_key: str | None = None):
            super().__init__()
            self._url = server_url.rstrip("/") + "/api/events/raw"
            self._api_key = api_key
            self._buffer: list[str] = []
            self._lock = threading.Lock()
            self._timer: threading.Timer | None = None
            self._start_timer()

        def _start_timer(self) -> None:
            self._timer = threading.Timer(2.0, self._flush)
            self._timer.daemon = True
            self._timer.start()

        def emit(self, record: logging.LogRecord) -> None:
            try:
                ts = datetime.datetime.fromtimestamp(
                    record.created, tz=datetime.timezone.utc
                ).isoformat()
                entry = json.dumps({
                    "@t": ts,
                    "@mt": record.getMessage(),
                    "@l": self._LEVEL_MAP.get(record.levelname, record.levelname),
                    "LoggerName": record.name,
                    "from": "theswarm",
                })
                with self._lock:
                    self._buffer.append(entry)
                    if len(self._buffer) >= 10:
                        self._flush_locked()
            except Exception:
                self.handleError(record)

        def _flush(self) -> None:
            with self._lock:
                self._flush_locked()
            self._start_timer()

        def _flush_locked(self) -> None:
            if not self._buffer:
                return
            payload = "\n".join(self._buffer)
            self._buffer.clear()
            threading.Thread(target=self._send, args=(payload,), daemon=True).start()

        def _send(self, payload: str) -> None:
            try:
                req = urllib.request.Request(
                    self._url, data=payload.encode(),
                    headers={"Content-Type": "application/vnd.serilog.clef"},
                )
                if self._api_key:
                    req.add_header("X-Seq-ApiKey", self._api_key)
                urllib.request.urlopen(req, timeout=5)
            except Exception:
                pass

    handler = _SeqCLEFHandler(seq_url, seq_api_key or None)
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)


# ── Settings loader (from old main.py) ───────────────────────────────

def _load_settings():
    """Load SwarmSettings from YAML + env vars."""
    from theswarm_common.config import MattermostConfig, ServerConfig, OllamaConfig, load_yaml_with_env
    from pydantic import BaseModel
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class SwarmPoConfig(BaseModel):
        enabled: bool = False
        llm_backend: str = "claude-code"
        github_repos: list[str] = []
        default_repo: str = ""
        team_channel: str = "swarm-team"
        channel: str = "swarm-bots-logs"
        mm_token: str = ""

    class AgentsConfig(BaseModel):
        swarm_po: SwarmPoConfig = SwarmPoConfig()

    class SwarmSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_prefix="THESWARM__",
            env_nested_delimiter="__",
            extra="ignore",
        )
        mattermost: MattermostConfig = MattermostConfig()
        ollama: OllamaConfig = OllamaConfig()
        server: ServerConfig = ServerConfig(port=8091)
        agents: AgentsConfig = AgentsConfig()

    yaml_data = load_yaml_with_env("theswarm.yaml")

    if token := os.getenv("SWARM_PO_MATTERMOST_TOKEN") or os.getenv("SWARM_PO_MM_TOKEN"):
        yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})["mm_token"] = token
    if repo := os.getenv("SWARM_PO_GITHUB_REPO"):
        sp = yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})
        repos = sp.get("github_repos", [])
        if repo not in repos:
            repos.append(repo)
        sp["github_repos"] = repos
        if not sp.get("default_repo"):
            sp["default_repo"] = repo
    if repos_str := os.getenv("SWARM_PO_GITHUB_REPOS"):
        sp = yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})
        sp["github_repos"] = [r.strip() for r in repos_str.split(",") if r.strip()]

    yaml_data.setdefault("server", {})["port"] = 8091

    server = yaml_data.get("server", {})
    ext_url = server.get("external_url", "")
    if ext_url and not ext_url.rstrip("/").endswith("/swarm"):
        server["external_url"] = ext_url.rstrip("/") + "/swarm"

    return SwarmSettings(**yaml_data)


# ── Keyword NLU ──────────────────────────────────────────────────────

class _KeywordNLU:
    """Simple keyword-based NLU for DM intent classification."""

    async def parse_intent(self, message: str, bot_name: str, known_actions: list[str]):
        from theswarm_common.chat import Intent
        msg = message.lower().strip()

        keywords = {
            "ping": "ping",
            "help": "help",
            "aide": "help",
            "status": "show_status",
            "plan": "show_plan",
            "plan du jour": "show_plan",
            "rapport": "show_report",
            "report": "show_report",
            "backlog": "list_stories",
            "issues": "list_stories",
            "go": "run_cycle",
            "start": "run_cycle",
            "lance": "run_cycle",
            "repos": "list_repos",
        }

        for keyword, action in keywords.items():
            if keyword in msg:
                return Intent(action=action, confidence=0.9, params={}, raw_text=message)

        if len(msg) > 10:
            return Intent(action="create_stories", confidence=0.6, params={}, raw_text=message)

        return Intent(action="unknown", confidence=0.1, params={}, raw_text=message)


# ── Mattermost connection ────────────────────────────────────────────

async def _connect_mattermost(config, server_config=None, label: str = "", callback_token: str = ""):
    if not config.base_url or not config.bot_token:
        return None
    from theswarm_common.chat.mattermost import MattermostAdapter
    adapter = MattermostAdapter(config, server_config, callback_token=callback_token)
    try:
        await adapter.connect()
        log.info("Mattermost [%s]: connected", label)
        return adapter
    except Exception as e:
        log.error("Mattermost [%s]: failed to connect: %s", label, e)
        return None


# ── Gateway state (for persona/wiring backward compat) ───────────────

class GatewayBridge:
    """Thin object that the persona.py and wiring.py modules expect.

    Replaces the old SwarmGateway class. Only carries the state and methods
    that persona/wiring actually use.
    """

    def __init__(self) -> None:
        self.callback_token: str = secrets.token_urlsafe(32)
        self._handlers: dict[str, list] = {}

        # Swarm PO state
        self._swarm_po_chat = None
        self._swarm_po_team_chat = None
        self._swarm_po_github = None
        self._swarm_po_vcs_map: dict[str, object] = {}
        self._swarm_po_default_repo: str = ""
        self._swarm_po_config = None
        self._swarm_po_pending_stories: dict[str, dict] = {}
        self._swarm_po_cycle_running = False
        self._swarm_po_current_phase = ""

        self._nlu = _KeywordNLU()
        self.settings = None

    def register(self, event_type: str, handler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def route_event(self, event) -> None:
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception:
                log.exception("Error in handler for event_type=%s", event.event_type)

    async def route_dm_event(self, bot_name: str, message: str, user_id: str) -> None:
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


# ── Main startup ─────────────────────────────────────────────────────

async def start_server(host: str = "0.0.0.0", port: int = 8091, db_path: str = "") -> None:
    """Start the full TheSwarm server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s -- %(message)s",
    )
    _setup_seq_logging()

    # Startup validation
    validator = StartupValidator()
    result = validator.validate_and_log()

    # Load settings
    settings = _load_settings()

    # Database
    if not db_path:
        data_dir = os.path.expanduser("~/.swarm-data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "theswarm.db")

    conn = await init_db(db_path)
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    bus = EventBus()

    # Create v2 web app
    app = create_web_app(project_repo, cycle_repo, bus)

    # Create gateway bridge for Mattermost/persona integration
    bridge = GatewayBridge()
    bridge.settings = settings

    # Store bridge on app.state for routes to access
    app.state.gateway_bridge = bridge

    # ── Connect Mattermost ────────────────────────────────────────
    from theswarm_common.config import MattermostConfig

    swarm_po_chat = await _connect_mattermost(
        MattermostConfig(
            base_url=settings.mattermost.base_url,
            bot_token=settings.agents.swarm_po.mm_token,
            channel_name=settings.agents.swarm_po.channel,
        ),
        server_config=settings.server,
        label="@swarm-po",
        callback_token=bridge.callback_token,
    )

    # ── Connect GitHub ────────────────────────────────────────────
    github_token = os.getenv("GITHUB_TOKEN", "")
    vcs_map: dict[str, object] = {}
    github_repos = settings.agents.swarm_po.github_repos
    default_repo = settings.agents.swarm_po.default_repo
    if github_token and github_repos:
        from github import Github
        gh = Github(github_token)
        for repo_name in github_repos:
            try:
                vcs_map[repo_name] = gh.get_repo(repo_name)
                log.info("GitHub: connected to %s", repo_name)
            except Exception as e:
                log.error("GitHub: failed to connect to %s: %s", repo_name, e)

    # ── Wire Swarm PO ────────────────────────────────────────────
    if settings.agents.swarm_po.enabled:
        bridge.wire_swarm_po(
            vcs_map=vcs_map, default_repo=default_repo,
            chat=swarm_po_chat, team_chat=swarm_po_chat,
        )
        log.info("Swarm PO: ready (repos=%s, default=%s)", github_repos, default_repo)
    else:
        log.info("Swarm PO: disabled")

    # ── Mattermost callback route ────────────────────────────────
    from theswarm_common.models import AgentEvent
    import starlette.requests

    @app.post("/swarm/mattermost/callback")
    async def mattermost_callback(request: starlette.requests.Request):
        body = await request.json()
        context = body.get("context", {})

        if not secrets.compare_digest(
            context.get("_token", ""),
            bridge.callback_token,
        ):
            log.warning("Mattermost callback: invalid token")
            return JSONResponse(status_code=403, content={"error": "forbidden"})

        post_id = body.get("post_id", "")
        user_id = body.get("user_id", "")
        action_id = context.get("action_id", "") or body.get("action", "")
        agent_event = AgentEvent(
            event_type="chat_action",
            source="mattermost",
            payload={"action_id": action_id, "post_id": post_id, "user_id": user_id, "context": context},
        )
        await bridge.route_event(agent_event)
        return {"update": {"message": "Action received."}}

    # ── Legacy dashboard + API routes ────────────────────────────
    # Mount old dashboard routes under /swarm/ prefix for backward compat
    from theswarm.dashboard import register_dashboard_routes, get_dashboard_state
    register_dashboard_routes(app)

    # Set dashboard state for legacy routes
    dash = get_dashboard_state()
    dash.github_repo = default_repo
    ext_url = getattr(settings.server, "external_url", "")
    if ext_url:
        dash.base_url = ext_url.rstrip("/")

    # Headless API
    from theswarm.api import register_api_routes
    register_api_routes(app, allowed_repos=github_repos)

    # ── WS listener for DMs ──────────────────────────────────────
    if swarm_po_chat:
        async def _on_ws_message(event: dict) -> None:
            try:
                data = event.get("data", {})
                post_raw = data.get("post", "{}")
                post = json.loads(post_raw) if isinstance(post_raw, str) else post_raw
                channel_type = data.get("channel_type", "")
                channel_name = data.get("channel_name", "")
                message = post.get("message", "").strip()
                user_id = post.get("user_id", "")

                is_dm = channel_type == "D" or ("__" in channel_name and channel_type in ("D", ""))

                if is_dm:
                    if message and user_id:
                        asyncio.ensure_future(bridge.route_dm_event("swarm_po", message, user_id))
                else:
                    msg_lower = message.lower()
                    if msg_lower.startswith("!swarm-po") or msg_lower.startswith("/swarm-po"):
                        channel_id = post.get("channel_id", "")
                        agent_event = AgentEvent(
                            event_type="chat_message",
                            source="mattermost",
                            payload={"message": message, "channel_id": channel_id, "post": post},
                        )
                        await bridge.route_event(agent_event)
            except Exception:
                log.exception("Error handling WS message")

        swarm_po_chat.on_message(_on_ws_message)

    # ── Startup banner ────────────────────────────────────────────
    status = "ready" if settings.agents.swarm_po.enabled else "disabled"
    log.info("")
    log.info("========================================")
    log.info("  TheSwarm v1.0 (unified)")
    log.info("========================================")
    log.info("  Swarm-PO:  %s", status)
    log.info("  GitHub:    %s repo(s)", len(vcs_map))
    log.info("  Chat:      %s", "connected" if has_chat else "not configured")
    log.info("  Dashboard: http://%s:%s", host, port)
    log.info("  Database:  %s", db_path)
    log.info("========================================")
    log.info("")

    if swarm_po_chat and settings.agents.swarm_po.enabled:
        await swarm_po_chat.post_message(
            settings.agents.swarm_po.channel,
            "TheSwarm v1.0 online",
        )

    # ── Start WS listener ────────────────────────────────────────
    if swarm_po_chat:
        asyncio.create_task(swarm_po_chat.start_websocket())

    # ── Start uvicorn ────────────────────────────────────────────
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
