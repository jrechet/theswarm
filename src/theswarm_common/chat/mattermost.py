"""Mattermost adapter — ChatPort implementation via mattermostdriver (WS + REST)."""

from __future__ import annotations

import asyncio
import json as _json
import logging
import ssl
from typing import Any, Callable, Coroutine

from mattermostdriver import Driver

from theswarm_common.config import MattermostConfig, ServerConfig
from theswarm_common.chat.port import ChatPort

log = logging.getLogger(__name__)


class MattermostAdapter(ChatPort):
    """ChatPort backed by Mattermost via mattermostdriver."""

    def __init__(self, config: MattermostConfig, server_config: ServerConfig | None = None) -> None:
        self.config = config
        self.server_config = server_config
        self._driver: Driver | None = None
        self._channel_id: str | None = None
        self._bot_user_id: str | None = None
        self._message_callbacks: list[Callable[..., Coroutine]] = []
        self._action_callbacks: list[Callable[..., Coroutine]] = []
        self._dm_channel_cache: dict[str, str] = {}  # user_id -> dm_channel_id

    async def connect(self) -> None:
        """Connect to Mattermost (login + resolve channel)."""
        url = self.config.base_url.rstrip("/")
        # Strip protocol for mattermostdriver
        host = url.replace("https://", "").replace("http://", "")
        scheme = "https" if url.startswith("https") else "http"

        self._driver = Driver({
            "url": host,
            "token": self.config.bot_token,
            "scheme": scheme,
            "port": 443 if scheme == "https" else 80,
            "verify": True,
        })

        # mattermostdriver bug: Websocket.connect() uses ssl.Purpose.CLIENT_AUTH
        # instead of SERVER_AUTH. Replace the ssl module reference in the
        # websocket module's namespace with a proxy that fixes create_default_context.
        import types
        import mattermostdriver.websocket as _mmws
        _ssl_proxy = types.ModuleType("ssl_proxy")
        _ssl_proxy.__dict__.update(ssl.__dict__)
        _ssl_proxy.create_default_context = lambda **kw: ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH
        )
        _mmws.ssl = _ssl_proxy

        await asyncio.to_thread(self._driver.login)
        log.info("Mattermost: logged in to %s", self.config.base_url)

        # Store bot user ID to filter out own messages
        me = await asyncio.to_thread(self._driver.users.get_user, "me")
        self._bot_user_id = me["id"]
        log.info("Mattermost: bot user id = %s", self._bot_user_id)

        # Resolve channel name → ID (optional; DM-only bots may have no team channel)
        try:
            self._channel_id = await self._resolve_channel(self.config.channel_name)
            log.info("Mattermost: resolved channel '%s' → %s", self.config.channel_name, self._channel_id)
        except Exception as e:
            log.warning(
                "Mattermost: could not resolve channel '%s' (bot may not be in any team): %s",
                self.config.channel_name, e,
            )
            self._channel_id = None

    async def _resolve_channel(self, channel_name: str) -> str:
        """Resolve a channel name to its ID."""
        user = await asyncio.to_thread(self._driver.users.get_user, "me")
        team_members = await asyncio.to_thread(self._driver.teams.get_user_teams, user["id"])
        for team in team_members:
            try:
                channel = await asyncio.to_thread(
                    self._driver.channels.get_channel_by_name, team["id"], channel_name
                )
                return channel["id"]
            except Exception:
                continue
        raise ValueError(f"Channel '{channel_name}' not found in any team")

    async def post_message(self, channel: str, text: str) -> str:
        """Post a simple text message. channel can be a name or ID."""
        channel_id = self._channel_id if channel == self.config.channel_name else channel
        resp = await asyncio.to_thread(
            self._driver.posts.create_post,
            {"channel_id": channel_id, "message": text},
        )
        post_id = resp.get("id", "")
        log.debug("Posted message %s to channel %s", post_id, channel_id)
        return post_id

    async def post_dm(self, user_id: str, text: str) -> str:
        """Open (or reuse) a DM channel with a user and post the message."""
        if user_id not in self._dm_channel_cache:
            bot_id = self._bot_user_id
            channel = await asyncio.to_thread(
                self._driver.channels.create_direct_message_channel,
                [bot_id, user_id],
            )
            self._dm_channel_cache[user_id] = channel["id"]
            log.debug("Opened DM channel %s with user %s", channel["id"], user_id)
        channel_id = self._dm_channel_cache[user_id]
        resp = await asyncio.to_thread(
            self._driver.posts.create_post,
            {"channel_id": channel_id, "message": text},
        )
        post_id = resp.get("id", "")
        log.debug("Posted DM %s to user %s", post_id, user_id)
        return post_id

    async def post_dm_interactive(
        self, user_id: str, text: str, actions: list[dict[str, Any]]
    ) -> str:
        """Post an interactive message (with buttons) as a DM to a user."""
        if user_id not in self._dm_channel_cache:
            bot_id = self._bot_user_id
            channel = await asyncio.to_thread(
                self._driver.channels.create_direct_message_channel,
                [bot_id, user_id],
            )
            self._dm_channel_cache[user_id] = channel["id"]
        channel_id = self._dm_channel_cache[user_id]
        return await self.post_interactive(channel_id, text, actions)

    async def post_interactive(
        self, channel: str, text: str, actions: list[dict[str, Any]]
    ) -> str:
        """Post a message with interactive buttons (Mattermost attachments format)."""
        channel_id = self._channel_id if channel == self.config.channel_name else channel

        # Build callback URL from server config (external_url for public reachability)
        callback_url = ""
        if self.server_config:
            if self.server_config.external_url:
                base = self.server_config.external_url.rstrip("/")
                callback_url = f"{base}/mattermost/callback"
            else:
                callback_url = f"http://{self.server_config.host}:{self.server_config.port}/mattermost/callback"
        log.info(
            "INTERACTIVE: building buttons — callback_url=%s, channel=%s, server_config=%s",
            callback_url, channel_id,
            f"host={self.server_config.host} port={self.server_config.port} ext={self.server_config.external_url}" if self.server_config else "None",
        )

        mm_actions = []
        for action in actions:
            action_id = action.get("id", "action")
            ctx = dict(action.get("context", {}))
            ctx["action_id"] = action_id
            mm_actions.append({
                "id": action_id,
                "name": action.get("name", "Action"),
                "style": action.get("style", "default"),
                "integration": {
                    "url": callback_url,
                    "context": ctx,
                },
            })

        payload = {
            "channel_id": channel_id,
            "message": text,
            "props": {
                "attachments": [{
                    "fallback": text,
                    "color": "#00CCFF",
                    "text": text,
                    "actions": mm_actions,
                }],
            },
        }

        resp = await asyncio.to_thread(self._driver.posts.create_post, payload)
        return resp.get("id", "")

    def on_message(self, callback: Callable[..., Coroutine]) -> None:
        """Register a callback for incoming messages."""
        self._message_callbacks.append(callback)

    def on_action(self, callback: Callable[..., Coroutine]) -> None:
        """Register a callback for interactive action clicks."""
        self._action_callbacks.append(callback)

    async def start_websocket(self) -> None:
        """Start the WebSocket listener in a background thread."""
        if not self._driver:
            raise RuntimeError("Must call connect() before start_websocket()")

        loop = asyncio.get_running_loop()

        bot_user_id = self._bot_user_id

        async def _ws_handler(event) -> None:
            # mattermostdriver passes raw JSON strings from websockets
            if isinstance(event, str):
                try:
                    event = _json.loads(event)
                except (ValueError, TypeError):
                    return
            if isinstance(event, dict) and event.get("event") == "posted":
                # Ignore bot's own messages to prevent loops
                data = event.get("data", {})
                post_raw = data.get("post", "{}")
                try:
                    post = _json.loads(post_raw) if isinstance(post_raw, str) else post_raw
                except (ValueError, TypeError):
                    post = {}
                if post.get("user_id") == bot_user_id:
                    return
                for cb in self._message_callbacks:
                    loop.call_soon_threadsafe(asyncio.ensure_future, cb(event))

        def _run_ws() -> None:
            # mattermostdriver.init_websocket needs an event loop in its thread
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            try:
                self._driver.init_websocket(_ws_handler)
            finally:
                ws_loop.close()

        await asyncio.to_thread(_run_ws)
