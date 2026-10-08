"""The PO tells the customer what was built (V3 plan: folded into the PO).

When a demo lands (`DemoReady`, after the report is stored) one Claude
call — the PO's voice, the text profile, no workspace — turns the
report's stories and checks, and the customer's own words when the
feature came from a request, into a headline and two or three plain
sentences. They are what a member reads first: on their feature page, in
their list of demos, above the player.

Three rules the prompt states and the code keeps:
- **Plain words.** No pull request numbers, branches, costs, test counts,
  cycle ids, links. A draft that names any (`leaks`) is asked again once
  with the offending words named, and skipped when it still does.
- **Honest.** The verdict of the running app goes in: a broken demo is
  not described as working, an unverified one says it was not fully
  checked.
- **Never at the cost of anything else.** Once per report; any failure — a
  shut subscription window, a timeout, a draft that named machinery twice —
  is a `skipped` row with its reason (the owner sees why and can ask
  again) and raises nothing.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable

from theswarm.agents.schemas import CustomerSummary
from theswarm.domain.reporting.summary import SKIPPED, WRITTEN, DemoSummary

log = logging.getLogger(__name__)

SUMMARY_TIMEOUT_SECONDS = 180
HEADLINE_MAX = 90
BODY_MAX = 700
ASKED_MAX_CHARS = 1500  # of the customer's own words in the prompt

# What a customer must never read: machinery. Each pattern names itself in
# the repair prompt.
_LEAKS = (
    (re.compile(r"https?://\S+"), "a link"),
    (re.compile(r"(?<![\w&])#\d+"), "an issue or pull request number"),
    (re.compile(r"\b(?:PR|pull request)s?\s*#?\d+", re.IGNORECASE), "a pull request number"),
    (re.compile(r"\$\s?\d"), "a cost"),
    (re.compile(r"\b[0-9a-f]{12}\b"), "a cycle id"),
    (re.compile(r"\b(?:feat|fix|chore)/[\w./-]+"), "a branch name"),
    (re.compile(r"\b\d+\s*(?:/|of)\s*\d+\s+tests?\b|\b\d+\s+tests?\s+(?:pass|passed|passing|failed)\b", re.IGNORECASE), "a test count"),
)

GATE_WORDS = {
    "feature_pages": "the new pages were opened on the running app",
    "feature_calls": "the new requests were played against the running app",
    "feature_e2e": "tests written for this feature were run against the running app",
}

SUMMARY_PROMPT = """You are the product owner of a small software team. A feature you asked your developers for has just been delivered, and you write the two or three sentences the customer who asked for it will read first.

What the customer asked for, in their words:
{asked}

What was delivered (the team's own titles, not for quotation):
{stories}

What the running app said when it was checked: {verdict}
{checks}

Write for a person who is not a developer:
- `headline`: at most {headline_max} characters, what they can now do, in the present tense ("You can now …").
- `body`: two or three short sentences, at most {body_max} characters. Say what changed for them and where they will see it, in their own vocabulary. Then, if the check above is not "verified", say so plainly in one sentence: a "broken" check means something did not work when it was tried and the team is looking at it; an "unverified" one means it was delivered but not fully tried out yet. Never describe a broken or unverified delivery as simply working.
- Never write a link, a number of pull requests, issues, tests or files, a cost, a branch, an id, or words like "pipeline", "merge", "commit", "endpoint", "API", "QA". Do not thank anyone and do not sign.
"""

REPAIR_PROMPT = """Your draft named machinery the customer should never read ({leaks}). Rewrite it without them: same facts, plain words, same two fields.

Your draft:
headline: {headline}
body: {body}
"""


def leaks(text: str) -> list[str]:
    """The kinds of machinery a draft names, each once, in order."""
    found = []
    for pattern, name in _LEAKS:
        if pattern.search(text or "") and name not in found:
            found.append(name)
    return found


def build_prompt(report: Any, verdict: str, asked: str) -> str:
    stories = "\n".join(f"- {s.title} ({s.status})" for s in report.stories) or "- (the report lists no story)"
    gates = [GATE_WORDS[g.name] + f": {str(getattr(g.status, 'value', g.status))}"
             for g in report.quality_gates if g.name in GATE_WORDS]
    checks = ("The checks: " + "; ".join(gates)) if gates else "No check was run on the running app."
    return SUMMARY_PROMPT.format(
        asked=(asked or "").strip()[:ASKED_MAX_CHARS] or "(the feature was planned by the team; no request from the customer is recorded)",
        stories=stories, verdict=verdict, checks=checks, headline_max=HEADLINE_MAX, body_max=BODY_MAX,
    )


def _tidy(headline: str, body: str) -> tuple[str, str]:
    """One line of headline, a body without markdown scaffolding, both capped."""
    head = re.sub(r"\s+", " ", (headline or "")).strip(" #*-").strip()[:HEADLINE_MAX].rstrip()
    text = re.sub(r"[ \t]+", " ", (body or "")).strip()
    text = re.sub(r"^[#*-]+[ ]*", "", text, flags=re.MULTILINE)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)[:BODY_MAX].rstrip()
    return head, text


async def write_summary(report: Any, claude: Any, *, verdict: str, asked: str = "", by: str = "PO") -> DemoSummary:
    """One call, one repair at most. Returns a `written` or `skipped` summary; raises only
    what must stop everything (a shut subscription window — the caller decides)."""
    prompt = build_prompt(report, verdict, asked)
    draft: CustomerSummary | None = None
    for attempt in range(2):
        result = await claude.run(prompt, timeout=SUMMARY_TIMEOUT_SECONDS, output_schema=CustomerSummary.model_json_schema())
        structured = getattr(result, "structured", None)
        if not structured:
            return DemoSummary(report_id=report.id, status=SKIPPED, written_by=by, reason="Claude answered no structured summary")
        draft = CustomerSummary.model_validate(structured)
        headline, body = _tidy(draft.headline, draft.body)
        named = leaks(f"{headline}\n{body}")
        if not named:
            if not headline or not body:
                return DemoSummary(report_id=report.id, status=SKIPPED, written_by=by, reason="the draft came back empty")
            return DemoSummary(report_id=report.id, status=WRITTEN, headline=headline, body=body, written_by=by)
        if attempt == 0:
            prompt = REPAIR_PROMPT.format(leaks=", ".join(named), headline=headline, body=body)
    return DemoSummary(report_id=report.id, status=SKIPPED, written_by=by,
                       reason=f"the draft named machinery twice ({', '.join(named)})")


class DemoSummaryWriter:
    """Writes the summary when a demo lands; the owner can ask again."""

    def __init__(self, report_repo: Any, summaries: Any, claude_factory: Callable[[], Any], *,
                 verdict_of: Callable[[Any], str],
                 asked_for: Callable[[str, int | None], Awaitable[str]] | None = None,
                 repo_of: Callable[[str], Awaitable[str]] | None = None) -> None:
        self._reports = report_repo
        self._summaries = summaries
        self._claude_factory = claude_factory
        self._verdict_of = verdict_of
        self._asked_for = asked_for
        self._repo_of = repo_of
        self._writing: dict[str, asyncio.Task] = {}

    def writing(self, report_id: str) -> bool:
        task = self._writing.get(report_id)
        return bool(task and not task.done())

    async def on_demo_ready(self, event: Any) -> None:
        """The bus subscriber: once per report, never the cycle's problem."""
        try:
            report_id = getattr(event, "report_id", "") or ""
            if not report_id or await self._summaries.get(report_id) is not None:
                return
            await self.write(report_id, issue_number=getattr(event, "issue_number", None))
        except Exception:  # noqa: BLE001
            log.exception("DemoSummary: the summary was not written")

    async def write(self, report_id: str, *, issue_number: int | None = None) -> DemoSummary | None:
        """Write (or write again) the summary of a report; None when the report is gone."""
        report = await self._reports.get(report_id)
        if report is None:
            return None
        asked = ""
        if self._asked_for is not None and issue_number:
            try:
                repo = await self._repo_of(report.project_id) if self._repo_of else report.project_id
                asked = await self._asked_for(repo, issue_number)
            except Exception:  # noqa: BLE001 — the words are a help, not a need
                log.exception("DemoSummary: reading what the customer asked failed")
        verdict = self._verdict_of(report.quality_gates)
        try:
            summary = await write_summary(report, self._claude_factory(), verdict=verdict, asked=asked)
        except Exception as exc:  # noqa: BLE001 — a shut window, a timeout: the row says why
            log.warning("DemoSummary: %s for report %s", exc.__class__.__name__, report_id)
            summary = DemoSummary(report_id=report_id, status=SKIPPED,
                                  reason=f"{exc.__class__.__name__}: {str(exc)[:160]}".strip(": "))
        await self._summaries.save(summary)
        return summary

    def start(self, report_id: str, *, issue_number: int | None = None) -> asyncio.Task:
        """The owner's click: the write runs in the background, the page answers now."""
        if not self.writing(report_id):
            self._writing[report_id] = asyncio.create_task(self.write(report_id, issue_number=issue_number))
        return self._writing[report_id]
