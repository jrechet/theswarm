"""NLU port and Intent model — protocol for intent classification from natural language messages."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class Intent(BaseModel):
    """Classified intent from a natural language message."""

    action: str
    """The action to perform, e.g. 'run_scan', 'implement_issue', 'review_pr'."""

    params: dict
    """Extracted params, e.g. {'issue_number': 42}."""

    confidence: float
    """Confidence from 0.0 to 1.0. Below 0.4 should be treated as 'unknown'."""

    raw_text: str
    """The original message, for logging / reply context."""


@runtime_checkable
class NLUPort(Protocol):
    async def parse_intent(self, message: str, agent: str, known_actions: list[str]) -> Intent:
        """
        Parse a natural language message into a structured Intent.

        :param message: The raw message from the user.
        :param agent: The agent name (e.g. 'logan', 'coddy', 'captain_q').
        :param known_actions: List of valid action strings for this agent.
        :return: An Intent with action, params, and confidence.
        """
        ...
