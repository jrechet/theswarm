"""Free personas at work (phase B, B3, second half).

`run_before_merge`: on a pull request the TechLead approved, each free
persona of the team placed before the merge reads it once per head and
answers a validated verdict. Its effect is the whole of its power: a
comment on the PR, or — `block` — the PR sent back to the Dev with its
findings, as a review's changes would be.

`run_after_qa`: once the feature is filmed, each persona placed after QA
reads what was delivered and comments on the feature's issue, once per
cycle.

A call that fails is a persona that did not speak: it never blocks a merge
and never fails a cycle (the owner added an opinion, not a new way to lose
a feature). Only an exhausted Claude window still stops everything.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from theswarm.agents.base import UNTRUSTED_NOTE, say
from theswarm.domain.teams.extras import AFTER_QA, BEFORE_MERGE, BLOCK
from theswarm.tools.claude import ClaudeFatalError

log = logging.getLogger(__name__)

STATUS_PREFIX = "theswarm/extra-"
DIFF_MAX_CHARS = 40_000
EXTRA_TIMEOUT_SECONDS = 300


class ExtraFinding(BaseModel):
    file: str = ""
    description: str


class ExtraVerdict(BaseModel):
    """What a free persona answers."""

    ok: bool = Field(description="true when nothing has to change")
    summary: str = Field(default="", description="One or two sentences")
    findings: list[ExtraFinding] = Field(default_factory=list)


BEFORE_MERGE_PROMPT = """\
You are **{name}**, an extra reviewer on this team. The Tech Lead has already approved this pull request; \
you look at one thing, the one your brief names, and nothing else.

## Your brief (written by the owner of this project)

{brief}

## Pull request #{number}: {title}

{body}

## Changed files

{diff}

{untrusted}

## Answer

`ok` is true when, for your brief, this pull request can merge as it is. When it is false, each finding \
names the file and what must change — only what your brief covers, nothing you would merely prefer. \
`summary` is one or two sentences.
"""

AFTER_QA_PROMPT = """\
You are **{name}**, an extra member of this team. A feature has just been built, merged and filmed; \
you write one note about it, the one your brief names.

## Your brief (written by the owner of this project)

{brief}

## What was delivered

{delivered}

## What QA measured

{gates}

{untrusted}

## Answer

`summary` is your note, in plain Markdown, ready to be posted as a comment on the feature's issue. \
`ok` is true unless your brief asks you to flag a problem and you found one; `findings` lists such problems.
"""


def placed(state, point: str) -> list[dict]:
    return [e for e in (state.get("extras") or []) if isinstance(e, dict) and e.get("point") == point]


def _claude_of(claude, extra: dict):
    model = extra.get("model") or ""
    if model and hasattr(claude, "with_settings"):
        return claude.with_settings(model)
    return claude


def _verdict(result) -> ExtraVerdict | None:
    structured = getattr(result, "structured", None)
    if not isinstance(structured, dict):
        return None
    try:
        return ExtraVerdict.model_validate(structured)
    except Exception:  # noqa: BLE001 — an answer in another shape is no answer
        return None


def _comment(extra: dict, verdict: ExtraVerdict, marker: str = "") -> str:
    """A persona's word as a comment. Before the merge it opens on its verdict;
    after QA it is a note, signed and nothing more — the first one on prod
    (concert-tour-app#977) read "Changelog writer — nothing to change"."""
    lines = [marker] if marker else []
    note = extra.get("point") == AFTER_QA and verdict.ok
    lines.append(f"**{extra['name']}**" if note
                 else f"**{extra['name']}** — {'nothing to change' if verdict.ok else 'something to change'}")
    if verdict.summary:
        lines += ["", verdict.summary]
    if verdict.findings:
        lines.append("")
        lines += [f"- {('`' + f.file + '`: ') if f.file else ''}{f.description}" for f in verdict.findings]
    return "\n".join(lines)


async def _earlier(github, sha: str, context: str) -> str:
    """"success" / "failure" when this persona already spoke on this head, "" otherwise."""
    try:
        checks = await github.get_ci_checks(sha)
    except Exception:  # noqa: BLE001 — unreadable: it speaks (once more at worst)
        return ""
    return next((str(c.get("state") or "") for c in checks if c.get("name") == context
                 and c.get("state") in ("success", "failure")), "")


async def _diff_of(github, number: int) -> str:
    from theswarm.agents.techlead import _format_files_diff

    text = _format_files_diff(await github.get_pr_files(number))
    return text if len(text) <= DIFF_MAX_CHARS else text[:DIFF_MAX_CHARS] + "\n… (the diff is longer; read the files in the repository)"


async def run_before_merge(state, github, pr: dict) -> dict:
    """Each free persona placed before the merge, on one approved PR.
    Returns {"blocked_by": the persona that sent it back or "", "spoke": [names], "cost_usd", "tokens"}."""
    out = {"blocked_by": "", "spoke": [], "cost_usd": 0.0, "tokens": 0}
    extras, claude = placed(state, BEFORE_MERGE), state.get("claude")
    sha = pr.get("head_sha") or ""
    if not extras or claude is None or not sha:
        return out
    diff = None
    for extra in extras:
        context = f"{STATUS_PREFIX}{extra['key']}"
        before = await _earlier(github, sha, context)
        if before == "success" or (before == "failure" and extra.get("effect") != BLOCK):
            continue  # it read this head already; a comment is not said twice
        if before == "failure":
            out["blocked_by"] = extra["name"]  # still blocking: the head has not moved
            break
        try:
            diff = diff if diff is not None else await _diff_of(github, pr["number"])
            await say(state, f"{extra['name']} reads PR #{pr['number']}")
            prompt = BEFORE_MERGE_PROMPT.format(
                name=extra["name"], brief=extra["prompt"], number=pr["number"], title=pr.get("title", ""),
                body=pr.get("body") or "(no description)", diff=diff, untrusted=UNTRUSTED_NOTE)
            result = await _claude_of(claude, extra).run(
                prompt, timeout=EXTRA_TIMEOUT_SECONDS, output_schema=ExtraVerdict.model_json_schema(),
                **({"workdir": state["workspace"]} if state.get("workspace") else {}))
        except ClaudeFatalError:
            raise
        except Exception as exc:  # noqa: BLE001 — a persona that did not speak blocks nothing
            log.warning("%s could not read PR #%s (%s: %s) — the merge goes on without it",
                        extra["name"], pr.get("number"), type(exc).__name__, str(exc)[:160])
            continue
        out["cost_usd"] += float(getattr(result, "cost_usd", 0.0) or 0.0)
        out["tokens"] += int(getattr(result, "total_tokens", 0) or 0)
        verdict = _verdict(result)
        if verdict is None:
            log.warning("%s answered PR #%s in no shape this code reads — the merge goes on without it",
                        extra["name"], pr.get("number"))
            continue
        out["spoke"].append(extra["name"])
        blocks = not verdict.ok and extra.get("effect") == BLOCK
        try:
            await github.create_commit_status(
                sha, "failure" if not verdict.ok else "success",
                f"{extra['name']}: {verdict.summary or ('nothing to change' if verdict.ok else 'something to change')}",
                context=context)
            if not verdict.ok or verdict.findings:
                await github.create_pr_comment(pr["number"], _comment(extra, verdict))
        except Exception:  # noqa: BLE001 — said in the logs at least
            log.exception("%s: its word on PR #%s could not be posted", extra["name"], pr.get("number"))
        log.info("%s on PR #%s: %s%s", extra["name"], pr["number"], "ok" if verdict.ok else "not ok",
                 " — blocks the merge" if blocks else "")
        if blocks:
            from theswarm.agents.techlead import _send_back_to_dev

            issues = [{"severity": "major", "file": f.file, "description": f.description} for f in verdict.findings]
            try:
                await _send_back_to_dev(github, pr, f"{extra['name']}: {verdict.summary}", issues,
                                        on_head=f"{extra['name']}: changes requested")
            except Exception:  # noqa: BLE001
                log.exception("PR #%s could not be sent back for %s", pr.get("number"), extra["name"])
            out["blocked_by"] = extra["name"]
            break
    return out


def _after_qa_marker(key: str, cycle_id: str) -> str:
    return f"<!-- swarm:extra {key} {cycle_id} -->"


async def run_after_qa(state, github, *, issue: int | None, cycle_id: str, delivered: list[dict],
                       demo_report: dict | None) -> dict:
    """Each free persona placed after QA: one comment on the feature's issue, once per cycle."""
    out = {"spoke": [], "cost_usd": 0.0, "tokens": 0}
    extras, claude = placed(state, AFTER_QA), state.get("claude")
    if not extras or claude is None or github is None or not issue:
        return out
    try:
        said = "\n".join(str(c.get("body") or "") for c in await github.get_issue_comments(issue))
    except Exception:  # noqa: BLE001
        said = ""
    listing = "\n".join(f"- PR #{p.get('number')}: {p.get('title', '')}" for p in delivered if isinstance(p, dict)) \
        or "(no pull request: the work was already on main)"
    gates = (demo_report or {}).get("quality_gates") or {}
    measured = "\n".join(f"- {name}: {(gate or {}).get('status', '?')}" for name, gate in gates.items()
                         if isinstance(gate, dict)) or "(QA measured nothing)"
    for extra in extras:
        marker = _after_qa_marker(extra["key"], cycle_id)
        if marker in said:
            continue  # this node ran once already (a resume): not said twice
        try:
            await say(state, f"{extra['name']} writes its note")
            prompt = AFTER_QA_PROMPT.format(name=extra["name"], brief=extra["prompt"], delivered=listing,
                                            gates=measured, untrusted=UNTRUSTED_NOTE)
            result = await _claude_of(claude, extra).run(
                prompt, timeout=EXTRA_TIMEOUT_SECONDS, output_schema=ExtraVerdict.model_json_schema(),
                **({"workdir": state["workspace"]} if state.get("workspace") else {}))
        except ClaudeFatalError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("%s could not write its note (%s: %s)", extra["name"], type(exc).__name__, str(exc)[:160])
            continue
        out["cost_usd"] += float(getattr(result, "cost_usd", 0.0) or 0.0)
        out["tokens"] += int(getattr(result, "total_tokens", 0) or 0)
        verdict = _verdict(result)
        if verdict is None or not (verdict.summary or verdict.findings):
            continue
        try:
            await github.add_comment(issue, _comment(extra, verdict, marker))
            out["spoke"].append(extra["name"])
        except Exception:  # noqa: BLE001
            log.exception("%s: its note on #%s could not be posted", extra["name"], issue)
    return out
