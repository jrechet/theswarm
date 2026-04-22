"""Dashboard-native chat service.

Resolves addressing (``@Codename`` or implicit per-thread), classifies intent
via an injected NLU engine (with a rule-based fallback), persists both user
and agent messages, and emits domain events for SSE fan-out.

No Anthropic calls happen here — the NLU is pluggable via the ``NLUEngine``
protocol so tests can inject a deterministic fake.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from theswarm.domain.chat.threads import AuthorKind, ChatMessage, ChatThread
from theswarm.domain.chat.value_objects import Intent, IntentAction
from theswarm.infrastructure.chat.chat_repo import SQLiteChatRepository

log = logging.getLogger(__name__)


# ── Ports ────────────────────────────────────────────────────────────


class NLUPort(Protocol):
    async def parse_intent(
        self,
        message: str,
        bot_name: str,
        known_actions: list[str],
    ): ...


class RoleLookupPort(Protocol):
    async def codename_map(self, project_id: str) -> dict[str, str]: ...

    async def list_for_project(
        self, project_id: str, include_retired: bool = False,
    ) -> list: ...


# ── Fallback NLU (pure rules, no LLM) ────────────────────────────────


_KEYWORD_TABLE: tuple[tuple[str, IntentAction], ...] = (
    ("run cycle", IntentAction.RUN_CYCLE),
    ("launch cycle", IntentAction.RUN_CYCLE),
    ("start cycle", IntentAction.RUN_CYCLE),
    ("status", IntentAction.SHOW_STATUS),
    ("plan", IntentAction.SHOW_PLAN),
    ("report", IntentAction.SHOW_REPORT),
    ("list stories", IntentAction.LIST_STORIES),
    ("list projects", IntentAction.LIST_PROJECTS),
    ("list repos", IntentAction.LIST_REPOS),
    ("add project", IntentAction.ADD_PROJECT),
    ("schedule", IntentAction.SCHEDULE),
    ("improvements", IntentAction.IMPROVEMENTS),
    ("ping", IntentAction.PING),
    ("help", IntentAction.HELP),
)


class RuleBasedNLU:
    """Keyword NLU fallback used when no LLM NLU is configured."""

    async def parse_intent(
        self,
        message: str,
        bot_name: str = "",
        known_actions: list[str] | None = None,
    ) -> Intent:
        msg = message.lower().strip()
        for keyword, action in _KEYWORD_TABLE:
            if keyword in msg:
                return Intent(action=action, confidence=0.8, raw_text=message)
        return Intent(action=IntentAction.UNKNOWN, confidence=0.1, raw_text=message)


# ── Result DTOs ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChatSendResult:
    thread: ChatThread
    user_message: ChatMessage
    agent_reply: ChatMessage | None
    intent: Intent
    resolved_codename: str = ""
    resolved_role: str = ""


# ── Service ──────────────────────────────────────────────────────────


_MENTION_RE = re.compile(r"@(?P<name>[A-Za-z][A-Za-z0-9_-]{1,30})")


class ChatService:
    """Route dashboard chat messages to agents and persist the conversation."""

    def __init__(
        self,
        chat_repo: SQLiteChatRepository,
        role_service: RoleLookupPort,
        nlu: NLUPort | None = None,
        event_bus=None,
    ) -> None:
        self._chat = chat_repo
        self._roles = role_service
        self._nlu = nlu or RuleBasedNLU()
        self._bus = event_bus

    async def send_user_message(
        self,
        *,
        project_id: str,
        body: str,
        author_id: str = "human",
        author_display: str = "You",
        thread_codename: str = "",
    ) -> ChatSendResult:
        """Persist a human message and produce an agent reply."""
        target_codename, target_role, stripped = await self._resolve_target(
            project_id=project_id, body=body, thread_codename=thread_codename,
        )
        thread = await self._chat.get_or_create_thread(
            project_id=project_id,
            codename=target_codename,
            role=target_role,
        )
        intent = await self._classify(stripped, target_codename or "swarm")

        user_msg = ChatMessage(
            id=ChatMessage.new_id(),
            thread_id=thread.id,
            author_kind=AuthorKind.HUMAN,
            author_id=author_id,
            author_display=author_display,
            body=body,
            intent_action=intent.action.value if isinstance(intent.action, IntentAction) else str(intent.action),
            intent_confidence=intent.confidence,
        )
        await self._chat.append_message(user_msg)
        self._emit("ChatMessagePosted", {"message": user_msg, "thread": thread})

        reply = await self._compose_reply(
            thread=thread,
            intent=intent,
            target_codename=target_codename,
            target_role=target_role,
            user_body=stripped,
        )
        if reply is not None:
            await self._chat.append_message(reply)
            self._emit("ChatMessagePosted", {"message": reply, "thread": thread})

        return ChatSendResult(
            thread=thread,
            user_message=user_msg,
            agent_reply=reply,
            intent=intent,
            resolved_codename=target_codename,
            resolved_role=target_role,
        )

    async def _resolve_target(
        self, *, project_id: str, body: str, thread_codename: str,
    ) -> tuple[str, str, str]:
        """Return ``(codename, role, stripped_body)``."""
        match = _MENTION_RE.search(body)
        if match:
            mention = match.group("name")
            # Strip the mention from the stripped body for NLU
            stripped = body.replace(match.group(0), "", 1).strip()
            role = await self._role_for_codename(project_id, mention)
            if role:
                return mention, role, stripped or body
            # mention didn't match any codename → fall through
        if thread_codename:
            role = await self._role_for_codename(project_id, thread_codename)
            return thread_codename, role or "", body
        return "", "", body

    async def _role_for_codename(self, project_id: str, codename: str) -> str:
        try:
            assignments = await self._roles.list_for_project(
                project_id, include_retired=False,
            )
        except Exception:
            log.exception("role lookup failed for project %s", project_id)
            return ""
        for a in assignments:
            if getattr(a, "codename", "").lower() == codename.lower():
                role_obj = getattr(a, "role", "")
                return role_obj.value if hasattr(role_obj, "value") else str(role_obj)
        return ""

    async def _classify(self, body: str, bot_name: str) -> Intent:
        try:
            raw = await self._nlu.parse_intent(body, bot_name, [])
        except Exception:
            log.exception("NLU failed — defaulting to UNKNOWN")
            return Intent(action=IntentAction.UNKNOWN, confidence=0.0, raw_text=body)
        # Some NLU implementations return strings for actions — normalise to enum
        action = raw.action
        if isinstance(action, str):
            try:
                action = IntentAction(action)
            except ValueError:
                action = IntentAction.UNKNOWN
        return Intent(
            action=action,
            confidence=float(raw.confidence or 0.0),
            raw_text=raw.raw_text or body,
            params=dict(getattr(raw, "params", {}) or {}),
        )

    async def _compose_reply(
        self,
        *,
        thread: ChatThread,
        intent: Intent,
        target_codename: str,
        target_role: str,
        user_body: str,
    ) -> ChatMessage | None:
        """Produce a canned reply. Real agent replies arrive later via worker."""
        who = target_codename or "the team"
        role_label = f" ({target_role.upper()})" if target_role else ""
        action = intent.action.value if isinstance(intent.action, IntentAction) else str(intent.action)
        body = _REPLY_TEMPLATES.get(action, _REPLY_TEMPLATES["default"]).format(
            codename=who, role=role_label, user_text=user_body,
        )
        return ChatMessage(
            id=ChatMessage.new_id(),
            thread_id=thread.id,
            author_kind=AuthorKind.AGENT,
            author_id=target_codename or "swarm",
            author_display=f"{who}{role_label}".strip(),
            body=body,
            intent_action=action,
            intent_confidence=intent.confidence,
            reply_to="",  # we don't pre-compute; UI can chain by created_at
            metadata={"auto": True},
        )

    def _emit(self, name: str, payload: dict) -> None:
        # Reserved hook for future phases (SSE fan-out). EventBus expects
        # typed DomainEvents and an awaitable publish, neither of which are
        # shaped for ad-hoc dicts — we keep the no-op to document the seam.
        return


_REPLY_TEMPLATES: dict[str, str] = {
    "run_cycle": (
        "Got it — I'll kick off a cycle. Use the Cycles tab to follow progress."
    ),
    "show_status": (
        "Current status is available on the Overview tab; the latest cycle "
        "shows its live phase + budget there."
    ),
    "show_plan": (
        "The plan for today's cycle is on the Reports tab once it lands."
    ),
    "show_report": (
        "Reports are on the Reports tab — I'll tag you when the next one is ready."
    ),
    "list_stories": (
        "Story listing lives on the Backlog tab."
    ),
    "list_projects": (
        "See the Projects page for the full portfolio."
    ),
    "schedule": (
        "Schedules live on Settings → Schedule for each project."
    ),
    "improvements": (
        "I'll surface the improvement suggestions from the last retrospective."
    ),
    "ping": "pong ✅",
    "help": (
        "Try: `run cycle`, `status`, `list stories`, `list projects`, or "
        "`@Codename …` to address a specific agent."
    ),
    "unknown": (
        "I heard you, but I'm not sure what to do. Try `help` for a menu."
    ),
    "default": (
        "Noted — {codename}{role} will follow up. (intent: unmapped)"
    ),
}


def _timestamp() -> datetime:
    return datetime.now(timezone.utc)
