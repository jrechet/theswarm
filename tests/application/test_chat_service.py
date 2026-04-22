"""Tests for ChatService (Phase B)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from theswarm.application.services.chat_service import (
    ChatService,
    RuleBasedNLU,
)
from theswarm.domain.agents.entities import RoleAssignment
from theswarm.domain.agents.value_objects import AgentRole
from theswarm.domain.chat.value_objects import Intent, IntentAction
from theswarm.infrastructure.chat.chat_repo import SQLiteChatRepository
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "chat.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def chat_repo(db):
    return SQLiteChatRepository(db)


@dataclass
class _FakeRoleService:
    rosters: dict[str, list[RoleAssignment]]

    async def list_for_project(self, project_id, include_retired=False):
        return self.rosters.get(project_id, [])

    async def codename_map(self, project_id):
        roster = self.rosters.get(project_id, [])
        return {a.role.value: a.codename for a in roster}


def _mk_assignment(role: AgentRole, codename: str, project: str = "demo"):
    return RoleAssignment(
        id=RoleAssignment.new_id(),
        project_id=project,
        role=role,
        codename=codename,
    )


class TestRuleBasedNLU:
    async def test_keyword_ping_matches(self):
        nlu = RuleBasedNLU()
        intent = await nlu.parse_intent("ping", bot_name="", known_actions=[])
        assert intent.action is IntentAction.PING

    async def test_keyword_run_cycle_matches(self):
        nlu = RuleBasedNLU()
        intent = await nlu.parse_intent("please run cycle now", "", [])
        assert intent.action is IntentAction.RUN_CYCLE

    async def test_unknown_on_no_match(self):
        nlu = RuleBasedNLU()
        intent = await nlu.parse_intent("xyzzy", "", [])
        assert intent.action is IntentAction.UNKNOWN


class TestChatServiceRouting:
    async def test_posts_user_and_agent_reply(self, chat_repo):
        roles = _FakeRoleService(rosters={
            "demo": [_mk_assignment(AgentRole.PO, "Mei")],
        })
        svc = ChatService(chat_repo, roles)
        result = await svc.send_user_message(project_id="demo", body="ping")
        assert result.user_message.body == "ping"
        assert result.intent.action is IntentAction.PING
        assert result.agent_reply is not None
        assert result.agent_reply.body == "pong ✅"

    async def test_mention_resolves_codename_to_role(self, chat_repo):
        roles = _FakeRoleService(rosters={
            "demo": [
                _mk_assignment(AgentRole.PO, "Mei"),
                _mk_assignment(AgentRole.DEV, "Aarav"),
            ],
        })
        svc = ChatService(chat_repo, roles)
        result = await svc.send_user_message(
            project_id="demo", body="@Aarav status please",
        )
        assert result.resolved_codename == "Aarav"
        assert result.resolved_role == "dev"
        # Thread is per-codename, not the team-thread
        assert result.thread.codename == "Aarav"

    async def test_unknown_mention_falls_through_to_team_thread(self, chat_repo):
        roles = _FakeRoleService(rosters={
            "demo": [_mk_assignment(AgentRole.PO, "Mei")],
        })
        svc = ChatService(chat_repo, roles)
        result = await svc.send_user_message(
            project_id="demo", body="@Ghost hello",
        )
        assert result.resolved_codename == ""
        assert result.thread.codename == ""  # team thread

    async def test_thread_codename_used_when_no_mention(self, chat_repo):
        roles = _FakeRoleService(rosters={
            "demo": [_mk_assignment(AgentRole.PO, "Mei")],
        })
        svc = ChatService(chat_repo, roles)
        result = await svc.send_user_message(
            project_id="demo", body="help", thread_codename="Mei",
        )
        assert result.resolved_codename == "Mei"
        assert result.resolved_role == "po"

    async def test_custom_nlu_is_used(self, chat_repo):
        class _FakeNLU:
            async def parse_intent(self, msg, bot, actions):
                return Intent(
                    action=IntentAction.RUN_CYCLE, confidence=0.95,
                    raw_text=msg,
                )

        roles = _FakeRoleService(rosters={"demo": []})
        svc = ChatService(chat_repo, roles, nlu=_FakeNLU())
        result = await svc.send_user_message(project_id="demo", body="anything")
        assert result.intent.action is IntentAction.RUN_CYCLE
        assert result.agent_reply is not None
        assert "cycle" in result.agent_reply.body.lower()

    async def test_nlu_failure_falls_back_to_unknown(self, chat_repo):
        class _BoomNLU:
            async def parse_intent(self, msg, bot, actions):
                raise RuntimeError("LLM exploded")

        roles = _FakeRoleService(rosters={"demo": []})
        svc = ChatService(chat_repo, roles, nlu=_BoomNLU())
        result = await svc.send_user_message(project_id="demo", body="hello")
        assert result.intent.action is IntentAction.UNKNOWN
        # Message is still persisted despite the NLU failure
        assert result.user_message.id != ""

    async def test_message_persistence_roundtrip(self, chat_repo):
        roles = _FakeRoleService(rosters={"demo": []})
        svc = ChatService(chat_repo, roles)
        result = await svc.send_user_message(project_id="demo", body="ping")
        reloaded = await chat_repo.list_messages(result.thread.id)
        bodies = [m.body for m in reloaded]
        assert "ping" in bodies
        assert "pong ✅" in bodies
