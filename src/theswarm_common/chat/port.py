"""Chat port — protocol for messaging platforms."""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Protocol, runtime_checkable


@runtime_checkable
class ChatPort(Protocol):
    async def connect(self) -> None:
        """Connect to the chat platform."""
        ...

    async def post_message(self, channel: str, text: str) -> str:
        """Post a text message. Returns the message ID."""
        ...

    async def post_dm(self, user_id: str, text: str) -> str:
        """Open (or reuse) a DM channel with a user and post a message. Returns the message ID."""
        ...

    async def post_interactive(
        self, channel: str, text: str, actions: list[dict[str, Any]]
    ) -> str:
        """Post a message with interactive buttons. Returns the message ID."""
        ...

    def on_message(self, callback: Callable[..., Coroutine]) -> None:
        """Register a callback for incoming messages."""
        ...

    def on_action(self, callback: Callable[..., Coroutine]) -> None:
        """Register a callback for interactive action clicks."""
        ...
