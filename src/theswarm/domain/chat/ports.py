"""Ports for the Chat bounded context."""

from __future__ import annotations

from typing import Protocol

from theswarm.domain.chat.value_objects import ButtonAction, Intent, IntentAction


class ChatAdapter(Protocol):
    """Send messages via any chat platform."""

    async def post_dm(self, user_id: str, text: str) -> str: ...
    async def post_dm_interactive(
        self, user_id: str, text: str, actions: list[ButtonAction],
    ) -> str: ...
    async def post_channel(self, channel_id: str, text: str, thread_id: str = "") -> str: ...
    async def connect(self) -> None: ...


class NLUEngine(Protocol):
    """Parse user messages into intents."""

    async def parse_intent(
        self,
        message: str,
        persona: str,
        known_actions: list[IntentAction],
    ) -> Intent: ...
