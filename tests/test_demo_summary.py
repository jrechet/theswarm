"""The PO tells the customer what was built (docs/plans/2026-10-v3-one-product.md,
the idea folded into the PO): when a demo lands, one Claude call turns the
report and the customer's own words into a headline and a few plain
sentences — honest about the running app's checks, never naming machinery.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from theswarm.application.services import demo_summary as ds
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.summary import SKIPPED, WRITTEN, DemoSummary
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.persistence.summary_repo import SQLiteDemoSummaryRepository

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
GOOD = {"headline": "You can now export your invoices as a PDF",
        "body": "A new button on the invoices page gives you a PDF of the month. Accounting can open it straight away."}


def _gate(name, status):
    return QualityGate(name=name, status=QualityStatus(status))


def _report(rid="rep-1", gates=(), stories=None) -> DemoReport:
    return DemoReport(
        id=rid, cycle_id=CycleId("cafe1234cafe"), project_id="jrechet/espace-client", created_at=NOW,
        summary=ReportSummary(stories_completed=1, stories_total=1, prs_merged=2, cost_usd=2.77),
        stories=tuple(stories if stories is not None else (StoryReport(ticket_id="42", title="Export invoices as PDF", status="completed", pr_number=82),)),
        quality_gates=tuple(gates),
    )


class _Claude:
    """Answers a script of structured drafts, one per call, and keeps the prompts."""

    def __init__(self, *drafts, raises=None):
        self.drafts, self.prompts, self.raises = list(drafts), [], raises

    async def run(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        if self.raises:
            raise self.raises
        draft = self.drafts.pop(0) if self.drafts else None
        return SimpleNamespace(structured=draft, text="")


def _verdict(gates) -> str:
    statuses = [str(getattr(g.status, "value", g.status)) for g in gates]
    return "broken" if "fail" in statuses else ("verified" if "pass" in statuses else "unverified")


class TestWhatACustomerMustNotRead:
    @pytest.mark.parametrize("text,kind", [
        ("see https://github.com/jrechet/theswarm/pull/82", "a link"),
        ("done in PR 82 and #83", "a pull request number"),
        ("closes #83", "an issue or pull request number"),
        ("this cost $2.77", "a cost"),
        ("cycle cafe1234cafe finished", "a cycle id"),
        ("on branch feat/issue-42-export", "a branch name"),
        ("12 tests passed", "a test count"),
        ("4 of 5 tests", "a test count"),
    ])
    def test_machinery_is_named(self, text, kind):
        assert kind in ds.leaks(text)

    def test_plain_words_and_ordinary_numbers_are_left_alone(self):
        assert ds.leaks("You can now download your 3 latest invoices as a PDF, in under 2 minutes.") == []
        assert ds.leaks("") == []


class TestThePrompt:
    def test_the_customer_s_words_the_stories_the_verdict_and_the_checks(self):
        gates = (_gate("feature_pages", "pass"), _gate("feature_e2e", "fail"), _gate("security", "pass"))
        prompt = ds.build_prompt(_report(gates=gates), "broken", "Export invoices as PDF\nMonthly, for accounting")
        assert "Monthly, for accounting" in prompt and "- Export invoices as PDF (completed)" in prompt
        assert "What the running app said when it was checked: broken" in prompt
        assert "the new pages were opened on the running app: pass" in prompt
        assert "tests written for this feature were run against the running app: fail" in prompt
        assert "security" not in prompt and "2.77" not in prompt and "82" not in prompt  # no machinery, no cost, no PR number
        assert "never describe a broken or unverified delivery as simply working" in prompt.lower()

    def test_no_request_and_no_check_are_said_not_invented(self):
        prompt = ds.build_prompt(_report(stories=()), "unverified", "")
        assert "no request from the customer is recorded" in prompt and "No check was run on the running app." in prompt
        assert "(the report lists no story)" in prompt

    def test_the_customer_s_words_are_capped(self):
        prompt = ds.build_prompt(_report(), "verified", "§" * 5000)
        assert prompt.count("§") == ds.ASKED_MAX_CHARS


class TestWriting:
    async def test_a_clean_draft_is_written_tidy(self):
        claude = _Claude({"headline": "  ## You can now export invoices\n", "body": "A button.  \n\n- It gives a PDF.\n"})
        s = await ds.write_summary(_report(), claude, verdict="verified")
        assert s.status == WRITTEN and s.headline == "You can now export invoices" and s.body == "A button.\n\nIt gives a PDF."
        prompt, kw = claude.prompts[0]
        assert kw["timeout"] == ds.SUMMARY_TIMEOUT_SECONDS and kw["output_schema"]["properties"]["headline"]
        assert "workdir" not in kw  # the text profile: no workspace, no tools

    async def test_a_draft_that_names_machinery_is_asked_again_once_with_the_words_named(self):
        leaking = {"headline": "PR 82 adds PDF export", "body": "See https://github.com/x/y/pull/82. It costs $2.77."}
        claude = _Claude(leaking, GOOD)
        s = await ds.write_summary(_report(), claude, verdict="verified")
        assert s.status == WRITTEN and s.headline == GOOD["headline"] and len(claude.prompts) == 2
        repair = claude.prompts[1][0]
        assert "a link" in repair and "a pull request number" in repair and "a cost" in repair and "PR 82 adds PDF export" in repair

    async def test_a_draft_that_still_names_machinery_is_skipped_with_why(self):
        leaking = {"headline": "PR 82 adds PDF export", "body": "Done in PR 82."}
        s = await ds.write_summary(_report(), _Claude(leaking, leaking), verdict="verified")
        assert s.status == SKIPPED and "named machinery twice" in s.reason and not s.body

    async def test_nothing_structured_and_an_empty_draft_are_skipped(self):
        assert (await ds.write_summary(_report(), _Claude(None), verdict="verified")).reason == "Claude answered no structured summary"
        empty = await ds.write_summary(_report(), _Claude({"headline": "", "body": "  "}), verdict="verified")
        assert empty.status == SKIPPED and empty.reason == "the draft came back empty"

    async def test_the_caps_hold(self):
        s = await ds.write_summary(_report(), _Claude({"headline": "H" * 300, "body": "B" * 3000}), verdict="verified")
        assert len(s.headline) <= ds.HEADLINE_MAX and len(s.body) <= ds.BODY_MAX


@pytest.fixture()
async def summaries(tmp_path):
    conn = await init_db(str(tmp_path / "sum.db"))
    yield SQLiteDemoSummaryRepository(conn)
    await conn.close()


class _Reports:
    def __init__(self, *reports):
        self.by_id = {r.id: r for r in reports}

    async def get(self, report_id):
        return self.by_id.get(report_id)


class TestTheRepository:
    async def test_round_trip_many_and_written_again(self, summaries):
        await summaries.save(DemoSummary(report_id="a", headline="H", body="B", created_at=NOW))
        await summaries.save(DemoSummary(report_id="b", status=SKIPPED, reason="the window is shut", created_at=NOW))
        got = await summaries.get("a")
        assert got == DemoSummary(report_id="a", headline="H", body="B", created_at=NOW) and got.is_written
        many = await summaries.get_many(["a", "b", "nope", "a", ""])
        assert set(many) == {"a", "b"} and not many["b"].is_written and many["b"].reason == "the window is shut"
        assert await summaries.get_many([]) == {} and await summaries.get("nope") is None
        await summaries.save(DemoSummary(report_id="b", headline="H2", body="B2", created_at=NOW))
        assert (await summaries.get("b")).body == "B2" and (await summaries.get("b")).reason == ""


class TestTheWriter:
    def _writer(self, summaries, claude, *reports, asked=None):
        async def asked_for(repo, number):
            return asked(repo, number) if asked else ""

        async def repo_of(project_id):
            return project_id

        return ds.DemoSummaryWriter(_Reports(*reports), summaries, lambda: claude, verdict_of=_verdict,
                                    asked_for=asked_for, repo_of=repo_of)

    async def test_a_landing_demo_is_written_once_with_the_customer_s_words(self, summaries):
        claude = _Claude(GOOD, GOOD)
        seen = []
        writer = self._writer(summaries, claude, _report(gates=(_gate("feature_pages", "pass"),)),
                              asked=lambda repo, n: seen.append((repo, n)) or "Export invoices as PDF — monthly, for accounting")
        event = SimpleNamespace(report_id="rep-1", issue_number=42)
        await writer.on_demo_ready(event)
        stored = await summaries.get("rep-1")
        assert stored.is_written and stored.headline == GOOD["headline"] and stored.written_by == "PO"
        assert seen == [("jrechet/espace-client", 42)]
        prompt = claude.prompts[0][0]
        assert "monthly, for accounting" in prompt and "What the running app said when it was checked: verified" in prompt
        await writer.on_demo_ready(event)  # once per report
        assert len(claude.prompts) == 1

    async def test_a_failure_is_a_skipped_row_with_its_reason_and_raises_nothing(self, summaries):
        writer = self._writer(summaries, _Claude(raises=RuntimeError("You've hit your session limit")), _report())
        await writer.on_demo_ready(SimpleNamespace(report_id="rep-1", issue_number=None))
        row = await summaries.get("rep-1")
        assert row.status == SKIPPED and "session limit" in row.reason and not row.is_written

    async def test_the_owner_can_ask_again_after_a_skip(self, summaries):
        writer = self._writer(summaries, _Claude(raises=RuntimeError("window shut")), _report())
        await writer.on_demo_ready(SimpleNamespace(report_id="rep-1", issue_number=None))
        assert not (await summaries.get("rep-1")).is_written
        again = ds.DemoSummaryWriter(_Reports(_report()), summaries, lambda: _Claude(GOOD), verdict_of=_verdict)
        done = await again.write("rep-1")
        assert done.is_written and (await summaries.get("rep-1")).headline == GOOD["headline"]

    async def test_a_missing_report_a_missing_id_and_a_failing_reader_are_quiet(self, summaries):
        writer = self._writer(summaries, _Claude(GOOD), asked=lambda r, n: (_ for _ in ()).throw(RuntimeError("GitHub is down")))
        assert await writer.write("nope") is None
        await writer.on_demo_ready(SimpleNamespace(report_id="", issue_number=None))
        writer = self._writer(summaries, _Claude(GOOD), _report(), asked=lambda r, n: (_ for _ in ()).throw(RuntimeError("GitHub is down")))
        done = await writer.write("rep-1", issue_number=42)  # the customer's words are a help, not a need
        assert done.is_written

    async def test_start_runs_in_the_background_one_at_a_time(self, summaries):
        gate = asyncio.Event()

        class Slow(_Claude):
            async def run(self, prompt, **kw):
                await gate.wait()
                return await super().run(prompt, **kw)

        claude = Slow(GOOD)
        writer = self._writer(summaries, claude, _report())
        task = writer.start("rep-1")
        assert writer.writing("rep-1") and writer.start("rep-1") is task
        gate.set()
        done = await task
        assert done.is_written and not writer.writing("rep-1") and len(claude.prompts) == 1
