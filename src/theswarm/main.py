"""Entrypoint: load config, wire Swarm PO, start gateway."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from theswarm_common.config import MattermostConfig, ServerConfig, OllamaConfig, load_yaml_with_env
from theswarm_common.models import AgentEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

# ── Seq structured logging ───────────────────────────────────────────
_seq_url = os.getenv("SEQ_URL", "")
_seq_api_key = os.getenv("SEQ_API_KEY", "")
if _seq_url:
    import seqlog
    _console_handlers = list(logging.getLogger().handlers)
    seqlog.log_to_seq(
        server_url=_seq_url,
        api_key=_seq_api_key or None,
        level=logging.INFO,
        batch_size=10,
        auto_flush_timeout=2,
        override_root_logger=True,
    )
    for h in _console_handlers:
        logging.getLogger().addHandler(h)


# ── Minimal settings for swarm service ────────────────────────────────

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


def load_swarm_settings(config_path: str = "theswarm.yaml") -> SwarmSettings:
    """Load settings from YAML file, then override with env vars."""
    yaml_data = load_yaml_with_env(config_path)

    # Inject env vars
    if token := os.getenv("SWARM_PO_MATTERMOST_TOKEN") or os.getenv("SWARM_PO_MM_TOKEN"):
        yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})["mm_token"] = token
    # Backward compat: single SWARM_PO_GITHUB_REPO sets both github_repos and default_repo
    if repo := os.getenv("SWARM_PO_GITHUB_REPO"):
        sp = yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})
        repos = sp.get("github_repos", [])
        if repo not in repos:
            repos.append(repo)
        sp["github_repos"] = repos
        if not sp.get("default_repo"):
            sp["default_repo"] = repo
    # Comma-separated list overrides
    if repos_str := os.getenv("SWARM_PO_GITHUB_REPOS"):
        sp = yaml_data.setdefault("agents", {}).setdefault("swarm_po", {})
        sp["github_repos"] = [r.strip() for r in repos_str.split(",") if r.strip()]

    # Force server port for swarm service (shared YAML sets 8090 for platform)
    yaml_data.setdefault("server", {})["port"] = 8091

    # Append /swarm prefix to external_url so Mattermost button callbacks
    # are routed through Traefik's /swarm PathPrefix → theswarm container.
    # Without this, callbacks hit the platform service which silently drops them.
    server = yaml_data.get("server", {})
    ext_url = server.get("external_url", "")
    if ext_url and not ext_url.rstrip("/").endswith("/swarm"):
        server["external_url"] = ext_url.rstrip("/") + "/swarm"

    return SwarmSettings(**yaml_data)


# ── Mattermost connection helper ──────────────────────────────────────


async def _connect_mattermost(config: MattermostConfig, server_config=None, label: str = ""):
    """Helper: create, connect and return a MattermostAdapter, or None on failure."""
    if not config.base_url or not config.bot_token:
        return None
    from theswarm_common.chat.mattermost import MattermostAdapter
    adapter = MattermostAdapter(config, server_config)
    try:
        await adapter.connect()
        log.info("Mattermost [%s]: connected", label)
        return adapter
    except Exception as e:
        log.error("Mattermost [%s]: failed to connect: %s", label, e)
        return None


# ── Start ─────────────────────────────────────────────────────────────


async def start() -> None:
    settings = load_swarm_settings()

    from theswarm.gateway import SwarmGateway

    gw = SwarmGateway(settings)

    # ── NLU ────────────────────────────────────────────────────────────
    # Swarm uses a keyword-based NLU for intent classification on DMs.
    # This avoids depending on swarm_platform's LLM NLU adapter.
    gw._nlu = _KeywordNLU()

    # ── Connect @swarm-po Mattermost adapter ──────────────────────────
    swarm_po_chat = await _connect_mattermost(
        MattermostConfig(
            base_url=settings.mattermost.base_url,
            bot_token=settings.agents.swarm_po.mm_token,
            channel_name=settings.agents.swarm_po.channel,
        ),
        server_config=settings.server, label="@swarm-po",
    )

    # Team channel chat (uses same adapter, different channel)
    team_chat = swarm_po_chat

    # ── VCS (GitHub) — one client per allowed repo ─────────────────────
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

    # ── Wire Swarm PO ─────────────────────────────────────────────────
    if settings.agents.swarm_po.enabled:
        gw.wire_swarm_po(
            vcs_map=vcs_map, default_repo=default_repo,
            chat=swarm_po_chat, team_chat=team_chat,
        )
        log.info("Swarm PO: ready (repos=%s, default=%s)", github_repos, default_repo)
    else:
        log.info("Swarm PO: disabled")

    # ── Mattermost action callback ────────────────────────────────────
    import starlette.requests

    @gw.app.post("/swarm/mattermost/callback")
    async def mattermost_callback(request: starlette.requests.Request):
        body = await request.json()
        context = body.get("context", {})
        post_id = body.get("post_id", "")
        action_id = context.get("action_id", "") or body.get("action", "")
        agent_event = AgentEvent(
            event_type="chat_action",
            source="mattermost",
            payload={"action_id": action_id, "post_id": post_id, "context": context},
        )
        await gw.route_event(agent_event)
        return {"update": {"message": "Action received."}}

    # ── WS listener for @swarm-po DMs ─────────────────────────────────
    if swarm_po_chat:
        async def _on_swarm_po_ws(event: dict) -> None:
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
                        asyncio.ensure_future(gw.route_dm_event("swarm_po", message, user_id))
                else:
                    msg_lower = message.lower()
                    if msg_lower.startswith("!swarm-po") or msg_lower.startswith("/swarm-po"):
                        channel_id = post.get("channel_id", "")
                        agent_event = AgentEvent(
                            event_type="chat_message",
                            source="mattermost",
                            payload={"message": message, "channel_id": channel_id, "post": post},
                        )
                        await gw.route_event(agent_event)

            except Exception:
                log.exception("Error handling swarm-po WS message")

        swarm_po_chat.on_message(_on_swarm_po_ws)

    # ── Startup banner ────────────────────────────────────────────────
    status = "ready" if settings.agents.swarm_po.enabled else "disabled"
    log.info("")
    log.info("╔══════════════════════════════════════╗")
    log.info("║     🤖 TheSwarm v0.3               ║")
    log.info("╠══════════════════════════════════════╣")
    log.info("║  %s Swarm-PO            %s  ║",
             "✅" if status == "ready" else "⬚ ",
             f"{status:>17}")
    log.info("╠══════════════════════════════════════╣")
    log.info("║  Server: %s:%s  ║",
             settings.server.host, f"{settings.server.port!s:>17}")
    log.info("╚══════════════════════════════════════╝")
    log.info("")

    if swarm_po_chat and settings.agents.swarm_po.enabled:
        await swarm_po_chat.post_message(
            settings.agents.swarm_po.channel,
            f"🟢 **TheSwarm v0.3 online** — ✅ Swarm-PO",
        )

    # ── Start WebSocket listener ──────────────────────────────────────
    if swarm_po_chat:
        asyncio.create_task(swarm_po_chat.start_websocket())

    await gw.start()


# ── Keyword NLU fallback ──────────────────────────────────────────────


class _KeywordNLU:
    """Simple keyword-based NLU fallback when LLMNLUAdapter is not available."""

    async def parse_intent(self, message: str, bot_name: str, known_actions: list[str]):
        from theswarm_common.chat import Intent

        msg = message.lower().strip()

        keywords = {
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
                return Intent(action=action, confidence=0.9, params={})

        # Default: assume it's a feature description for story creation
        if len(msg) > 10:
            return Intent(action="create_stories", confidence=0.6, params={})

        return Intent(action="unknown", confidence=0.1, params={})


# ── Entry point ───────────────────────────────────────────────────────


def main() -> None:
    asyncio.run(start())


if __name__ == "__main__":
    main()
