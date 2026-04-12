"""Tests for domain/chat — 100% coverage target."""

from __future__ import annotations

from theswarm.domain.chat.entities import Conversation, Persona
from theswarm.domain.chat.value_objects import ButtonAction, Intent, IntentAction


class TestIntentAction:
    def test_key_values(self):
        assert IntentAction.CREATE_STORIES == "create_stories"
        assert IntentAction.RUN_CYCLE == "run_cycle"
        assert IntentAction.PING == "ping"
        assert IntentAction.HELP == "help"
        assert IntentAction.UNKNOWN == "unknown"
        assert IntentAction.LIST_PROJECTS == "list_projects"
        assert IntentAction.ADD_PROJECT == "add_project"
        assert IntentAction.SCHEDULE == "schedule"
        assert IntentAction.IMPROVEMENTS == "improvements"


class TestIntent:
    def test_confident(self):
        i = Intent(action=IntentAction.PING, confidence=0.95, raw_text="ping")
        assert i.is_confident is True

    def test_not_confident_low_score(self):
        i = Intent(action=IntentAction.PING, confidence=0.20)
        assert i.is_confident is False

    def test_not_confident_unknown(self):
        i = Intent(action=IntentAction.UNKNOWN, confidence=0.90)
        assert i.is_confident is False

    def test_params_default(self):
        i = Intent(action=IntentAction.HELP, confidence=1.0)
        assert i.params == {}


class TestButtonAction:
    def test_creation(self):
        b = ButtonAction(id="swarm_po_pong:ping", name="Pong", style="good")
        assert b.id == "swarm_po_pong:ping"
        assert b.style == "good"

    def test_default_style(self):
        b = ButtonAction(id="x", name="X")
        assert b.style == "default"


class TestPersona:
    def test_creation(self):
        p = Persona(
            name="swarm_po",
            display_name="Swarm PO",
            known_actions=(IntentAction.PING, IntentAction.HELP, IntentAction.RUN_CYCLE),
        )
        assert p.supports_action(IntentAction.PING) is True
        assert p.supports_action(IntentAction.CREATE_STORIES) is False

    def test_empty_actions(self):
        p = Persona(name="test", display_name="Test")
        assert p.supports_action(IntentAction.HELP) is False


class TestConversation:
    def test_creation(self):
        c = Conversation(user_id="u1", persona_name="swarm_po", project_id="my-app")
        assert c.user_id == "u1"
        assert c.started_at is not None
