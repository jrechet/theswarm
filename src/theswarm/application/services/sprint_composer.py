"""SprintComposer — turn a one-line user request into well-formed backlog issues.

The user types a sprint description in plain English. We send it to Claude
(via the same backend the agents use) with a structured prompt and parse
the response into a list of GitHub issue drafts. The dashboard previews
those drafts and the user confirms before they're created on GitHub.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssueDraft:
    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True)
class SprintDraft:
    request: str
    issues: tuple[IssueDraft, ...]
    raw_response: str = ""


_SYSTEM_PROMPT = """You are a senior product owner. The user will describe a small sprint of work.
Break it into 1 to 5 atomic GitHub issues. Each issue must be:
- Independently shippable (one PR each).
- Small enough for a single coding session (1-3 files of changes).
- Stated as a verb-first imperative title ("Add X", "Refactor Y", "Fix Z").

Return strict JSON, no markdown fences, no commentary. Schema:

{
  "issues": [
    {
      "title": "string, imperative, <=80 chars",
      "body": "string, markdown, includes Acceptance Criteria as a checklist",
      "labels": ["status:backlog", "role:dev", "component:..."]
    }
  ]
}

Always include "status:backlog" and "role:dev" in labels. Add one
"component:<name>" label inferred from the request when obvious
(api, ui, tests, docs, infra, etc.). Never include "status:ready" or
later — PO will move them through the pipeline.
"""


class SprintComposer:
    """Calls Claude to turn a free-form request into IssueDrafts."""

    def __init__(self, claude_factory):
        """``claude_factory`` returns a ClaudeCLI instance, e.g. ``lambda: ClaudeCLI(model='haiku')``."""
        self._claude_factory = claude_factory

    async def draft(self, request: str) -> SprintDraft:
        request = (request or "").strip()
        if not request:
            return SprintDraft(request="", issues=(), raw_response="")
        if len(request) > 4000:
            raise ValueError("sprint request too long (max 4000 chars)")

        cli = self._claude_factory()
        prompt = f"{_SYSTEM_PROMPT}\n\nUser request:\n{request}"
        result = await cli.run(prompt)
        text = (result.text or "").strip()
        return _parse_response(request, text)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_response(request: str, text: str) -> SprintDraft:
    """Extract the JSON envelope and coerce into IssueDrafts."""
    raw = text
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        log.warning("SprintComposer: no JSON block in response")
        return SprintDraft(request=request, issues=(), raw_response=raw)
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.warning("SprintComposer: JSON parse failed: %s", exc)
        return SprintDraft(request=request, issues=(), raw_response=raw)

    issues_in = payload.get("issues") or []
    issues_out: list[IssueDraft] = []
    for it in issues_in[:5]:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()[:200]
        if not title:
            continue
        body = (it.get("body") or "").strip()
        labels = it.get("labels") or []
        labels = tuple(
            l.strip() for l in labels if isinstance(l, str) and l.strip()
        )
        # Always enforce the two state labels.
        required = ("status:backlog", "role:dev")
        for r in required:
            if r not in labels:
                labels = labels + (r,)
        issues_out.append(IssueDraft(title=title, body=body, labels=labels))

    return SprintDraft(
        request=request,
        issues=tuple(issues_out),
        raw_response=raw,
    )
