"""Story generation and approval flow."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from theswarm.gateway.app import SwarmGateway

log = logging.getLogger(__name__)


async def generate_stories(gw: SwarmGateway, description: str) -> list[dict]:
    """Call Claude CLI to generate user stories from a feature description."""
    from theswarm.tools.claude import ClaudeCLI

    prompt = f"""\
You are a Product Owner. Generate user stories from this feature request.

Feature request: {description}

Return a JSON array of user stories:
[
    {{
        "title": "US: Short imperative title",
        "description": "As a [user], I want [goal] so that [benefit].\\n\\nAcceptance criteria:\\n- [ ] ..."
    }}
]

Rules:
- 2-5 stories, ordered by priority
- Each story must be independently implementable
- Include acceptance criteria
- Return ONLY the JSON array, no markdown fences.
"""
    try:
        cli = ClaudeCLI(model="sonnet")
        result = await cli.run(prompt, timeout=60)

        import re
        text = result.text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n", "", text)
            text = re.sub(r"\n```\s*$", "", text)

        stories = json.loads(text)
        if isinstance(stories, list):
            return stories
        if isinstance(stories, dict):
            return stories.get("stories", [])
    except Exception:
        log.exception("SwarmPO: failed to generate stories")
    return []


async def store_pending_stories(gw: SwarmGateway, user_id: str, stories: list[dict]) -> str:
    """Store stories pending approval, return a unique ID."""
    pending_id = uuid.uuid4().hex[:8]
    gw._swarm_po_pending_stories[pending_id] = {
        "user_id": user_id,
        "stories": stories,
    }
    return pending_id


async def create_issues(gw: SwarmGateway, user_id: str, stories: list[dict]) -> None:
    """Create GitHub issues from approved stories."""
    vcs = gw._swarm_po_github
    chat = gw._swarm_po_chat

    if not vcs:
        if chat:
            await chat.post_dm(user_id, "❌ GitHub not configured for SWARM PO.")
        return

    created = []
    loop = asyncio.get_running_loop()
    for story in stories:
        try:
            issue = await loop.run_in_executor(
                None,
                lambda s=story: vcs.create_issue(
                    title=s["title"],
                    body=s.get("description", ""),
                    labels=["status:backlog"],
                ),
            )
            created.append(f"#{issue.number}")
        except Exception as e:
            log.error("SwarmPO: failed to create issue: %s", e)

    if chat:
        if created:
            await chat.post_dm(
                user_id,
                f"✅ Created **{len(created)}** issues: {', '.join(created)}\n\nSay `go` to launch the dev cycle!",
            )
        else:
            await chat.post_dm(user_id, "❌ Failed to create issues.")
