"""The verdict is read wherever the reviewer put it.

Cycle 5f8f0f63f58c, PR #126: the TechLead opened with a paragraph of prose
("… unifies the `GET /api/cycles/{id}` shape …") and then gave its verdict
as a fenced ```json block — decision APPROVE, three issues. The parser
sliced from the first `{` (the one in `{id}`) to the last `}`, got garbage,
and the salvage regex would not read a quoted "decision" key. Filed as
COMMENT, issues thrown away, PR held for nothing.
"""

from __future__ import annotations

from theswarm.agents.techlead import _parse_review, _salvage_decision

FENCED_AFTER_PROSE = """Based on thorough static analysis (tracing the diff against the
domain entities), the PR correctly unifies the `GET /api/cycles/{id}` shape
with the merged-list shape, and the new tests exercise the real code paths.

```json
{
  "decision": "APPROVE",
  "summary": "Correctly unifies the GET /api/cycles/{id} response.",
  "issues": [
    {"severity": "minor", "file": "routes/api.py", "description": "project_id and repo carry the same value."},
    {"severity": "minor", "file": "routes/api.py", "description": "phases changes from int to list."},
    {"severity": "nit", "file": "tests/test_cycles_api.py", "description": "fakes are not checked against the port."}
  ]
}
```
"""

BARE_AFTER_PROSE = """I traced `{cycle_id}` through both stores; here is my verdict:
{"decision": "REQUEST_CHANGES", "summary": "The tracker branch drops created_at.", "issues": [
  {"severity": "major", "file": "routes/api.py", "description": "created_at is gone."}]}
Let me know if you want the diff."""


def test_a_fenced_verdict_after_prose_is_the_verdict():
    review, salvaged = _parse_review(FENCED_AFTER_PROSE)

    assert salvaged is False
    assert review["decision"] == "APPROVE"
    assert len(review["issues"]) == 3
    assert review["summary"].startswith("Correctly unifies")


def test_a_bare_object_after_prose_with_braces_is_found():
    review, salvaged = _parse_review(BARE_AFTER_PROSE)

    assert salvaged is False
    assert review["decision"] == "REQUEST_CHANGES"
    assert review["issues"][0]["severity"] == "major"


def test_a_stray_object_without_a_decision_is_not_the_review():
    """A JSON-looking example in the prose must not win over the real block."""
    text = 'Example payload: {"id": "abc", "status": "running"}\n\n```json\n{"decision": "APPROVE", "summary": "ok", "issues": []}\n```'

    review, salvaged = _parse_review(text)

    assert salvaged is False
    assert review["decision"] == "APPROVE"


def test_a_truncated_json_still_salvages_its_quoted_decision():
    """max_tokens hit mid-issues: no object parses, but the word is there."""
    text = '```json\n{\n  "decision": "REQUEST_CHANGES",\n  "summary": "Handler never updated",\n  "issues": [\n    {"severity": "critical", "file": "x.py", "description": "cut off he'

    review, salvaged = _parse_review(text)

    assert salvaged is True
    assert review["decision"] == "REQUEST_CHANGES"


def test_the_salvage_regex_reads_quoted_and_markdown_forms():
    assert _salvage_decision('"decision": "APPROVE"') == "APPROVE"
    assert _salvage_decision("**Decision:** REQUEST_CHANGES") == "REQUEST_CHANGES"
    assert _salvage_decision("Verdict — APPROVE") == "APPROVE"
    assert _salvage_decision("I have no strong opinion.") == "COMMENT"


def test_a_plain_json_review_is_unchanged():
    review, salvaged = _parse_review('{"decision": "APPROVE", "summary": "fine", "issues": []}')

    assert (review["decision"], salvaged) == ("APPROVE", False)
