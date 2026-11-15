"""Talking to a running cycle (A3.1): the owner's message waits in the
cycle's inbox and reaches whichever agent works next.

The owner (2026-11-11): "pouvoir interagir avec un agent en cours : chatter
une correction". A message is written down, shown in the theater's feed,
and delivered once — at the working agent's next tool call (the PreToolUse
hook's `additionalContext`) or at the head of the next Claude call's
prompt, whichever comes first. Nothing is interrupted: the agent reads it
between two steps, as a colleague's word. Stopping a call is A3.3.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000

# How the message is put to the agent. It is the owner's word on the task at
# hand, and it is said so: the agent works in a repository whose files and
# issues may hold text that only looks like an instruction.
DELIVERY_HEADING = (
    "A message from the owner of this cycle, sent while you were working. Take it into "
    "account for the task at hand; it does not replace the task or the form of the answer asked for:"
)


class InboxError(ValueError):
    """A message that cannot be taken, said in words for the owner."""


def delivery_text(messages: list[str]) -> str:
    """What the agent reads: the heading, then each message on its own line."""
    if not messages:
        return ""
    return DELIVERY_HEADING + "\n" + "\n".join(f"- {m}" for m in messages)


class CycleInbox:
    def __init__(self, repo, event_bus=None) -> None:
        self._repo = repo
        self._bus = event_bus

    async def _tell(self, cycle_id: str, project_id: str, action: str, detail: str) -> None:
        if self._bus is None:
            return
        from theswarm.domain.cycles.events import AgentActivity
        from theswarm.domain.cycles.value_objects import CycleId

        try:
            await self._bus.publish(AgentActivity(
                cycle_id=CycleId(cycle_id), project_id=project_id, agent="owner", action=action, detail=detail,
            ))
        except Exception:  # noqa: BLE001 — the message is kept; only its line is missing
            log.exception("The inbox of %s could not tell the feed", cycle_id)

    async def post(self, cycle_id: str, text: str, *, author: str = "", project_id: str = "") -> int:
        body = " ".join(str(text or "").split())
        if not body:
            raise InboxError("Write something to say.")
        if len(body) > MAX_MESSAGE_CHARS:
            raise InboxError(f"{MAX_MESSAGE_CHARS} characters at most.")
        message_id = await self._repo.add(cycle_id, body, author)
        await self._tell(cycle_id, project_id, "message", body)
        log.info("Cycle %s: a message from %s waits for the working agent (%d chars)",
                 cycle_id, author or "the owner", len(body))
        return message_id

    async def take(self, cycle_id: str, *, to: str = "", project_id: str = "") -> list[str]:
        """The messages no agent has read yet, read now by `to`. Never raises:
        a cycle does not fail on its inbox."""
        try:
            messages = await self._repo.take(cycle_id, to)
        except Exception:  # noqa: BLE001
            log.exception("The inbox of %s could not be read", cycle_id)
            return []
        if messages:
            count = "The message" if len(messages) == 1 else f"{len(messages)} messages"
            await self._tell(cycle_id, project_id, "message_read", f"{count} reached {to or 'the agent'}")
            log.info("Cycle %s: %d message(s) delivered to %s", cycle_id, len(messages), to or "the agent")
        return messages

    async def waiting(self, cycle_id: str) -> int:
        try:
            return await self._repo.waiting(cycle_id)
        except Exception:  # noqa: BLE001
            return 0
