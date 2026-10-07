"""DevOps D4 — what it measures (docs/plans/2026-10-v3-one-product.md).

The CI's pace per job off the last completed runs of the deploy workflow
on main (duration, the setup wait where the CI slot sits, failures), the
cycle's price off the harness's records; a `measures` finding on the
card that warns when the slot costs more than the job; the facts the
improvement PR will be written from.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from theswarm.agents import devops
from theswarm.agents.devops_measures import (
    JobMeasure,
    ci_measures,
    cycle_measure,
    job_dict,
    measures_facts,
    measures_finding,
)

T0 = datetime(2026, 10, 7, 17, 40, tzinfo=timezone.utc)
STACK = {"hosts": [], "ci": [{"provider": "github-actions", "repo": "jrechet/theswarm", "deploy_workflow": "ci.yml"}],
         "harness": {"repo": "jrechet/concert-tour-app"}}


def _job(name, minutes, setup=0.0, conclusion="success", run_id=1, start=T0):
    steps = [{"name": "Set up runner", "started_at": start, "completed_at": start + timedelta(minutes=setup)},
             {"name": "Run tests", "started_at": start + timedelta(minutes=setup), "completed_at": start + timedelta(minutes=minutes)}]
    return {"run_id": run_id, "name": name, "conclusion": conclusion, "started_at": start,
            "completed_at": start + timedelta(minutes=minutes), "steps": steps}


class TestTheMeasures:
    def test_per_job_median_p90_setup_and_failures_longest_first(self):
        jobs = [_job("tests", 9, run_id=i) for i in range(1, 8)] + [_job("tests", 30, conclusion="failure", run_id=8)]
        jobs += [_job("deploy / deploy", 35, setup=33, run_id=i) for i in range(1, 5)] + [_job("deploy / deploy", 2, setup=0.3, run_id=i) for i in range(5, 9)]
        jobs += [_job("deploy / build", 2, run_id=i) for i in range(1, 9)]
        out = ci_measures(jobs)
        assert [m.name for m in out] == ["deploy / deploy", "tests", "deploy / build"]
        tests = out[1]
        assert tests.runs == 8 and tests.median_min == 9 and tests.p90_min == 30 and tests.failures == 1 and tests.setup_min == 0
        deploy = out[0]
        assert deploy.runs == 8 and deploy.median_min == 18.5 and deploy.setup_min == 16.6 and deploy.slot_dominates

    def test_strings_and_missing_times_are_read_or_skipped(self):
        jobs = [{"name": "tests", "conclusion": "success", "started_at": "2026-10-07T17:40:00Z", "completed_at": "2026-10-07T17:49:30Z", "steps": []},
                {"name": "tests", "conclusion": None, "started_at": None, "completed_at": None, "steps": []},
                {"name": "", "started_at": T0, "completed_at": T0}]
        [m] = ci_measures(jobs)
        assert m.runs == 2 and m.median_min == 9.5 and m.failures == 0
        assert ci_measures([]) == []

    def test_a_pygithub_job_becomes_plain_values(self):
        step = SimpleNamespace(name="Set up runner", started_at=T0, completed_at=T0 + timedelta(minutes=12))
        job = SimpleNamespace(name="deploy / deploy", conclusion="success", started_at=T0, completed_at=T0 + timedelta(minutes=14), steps=[step], run_id=7)
        d = job_dict(job)
        assert d["name"] == "deploy / deploy" and d["run_id"] == 7 and d["steps"][0]["name"] == "Set up runner"
        [m] = ci_measures([d])
        assert m.median_min == 14 and m.setup_min == 12 and m.slot_dominates

    def test_the_cycle_s_price_off_the_harness_records(self):
        records = [{"cost_usd": 2.1, "duration_s": 2400}, {"cost_usd": 3.3, "duration_s": 3000}, {"cost_usd": 2.9}, {"built": True}]
        assert cycle_measure(records) == {"runs": 3, "cost_usd": 2.9, "duration_min": 45.0}
        assert cycle_measure([]) is None and cycle_measure([{"built": True}]) is None


class TestTheFinding:
    def test_the_words_and_the_warning_when_the_slot_costs_more_than_the_job(self):
        jobs = [JobMeasure("deploy / deploy", 8, 18.5, 35.0, 16.6, 0), JobMeasure("tests", 8, 9.0, 30.0, 0.0, 1), JobMeasure("deploy / build", 8, 2.0, 2.0, 0.0, 0)]
        f = measures_finding(jobs, {"runs": 7, "cost_usd": 2.4, "duration_min": 41.0})
        assert f.key == "measures" and f.status == "warn"
        assert f.detail.startswith("over 8 runs: deploy / deploy 18.5 min median (p90 35, 16.6 min of it setup wait); tests 9 min median (p90 30, 1 of 8 failed); deploy / build 2 min median")
        assert "a cycle costs $2.40 and 41 min median over 7 runs" in f.detail and "the CI slot) costs more than the job itself on deploy / deploy" in f.detail
        fine = measures_finding([JobMeasure("tests", 8, 9.0, 9.0, 0.3, 0)], None)
        assert fine.status == "ok" and fine.detail == "over 8 runs: tests 9 min median"
        assert measures_finding([], None).status == "unknown"
        assert measures_facts(jobs, None) == {"jobs": [j.as_dict() for j in jobs], "cycle": None}


class TestOnTheReport:
    async def test_the_report_carries_the_measures_when_the_reader_answers_jobs(self):
        async def github(repo):
            return {"main_sha": "a" * 40, "runners": [], "runs": [],
                    "jobs": [_job("tests", 9, run_id=i) for i in range(1, 4)], "devops_prs": [{"number": 307, "title": "ci: cache uv", "html_url": "u", "head": "devops/cache-uv"}]}

        async def harness(repo):
            return [{"cost_usd": 2.5, "duration_s": 1800, "timestamp": T0.isoformat(), "built": True, "feature": "x"}]

        report = await devops.gather(STACK, github=github, host_reader=None, claude=lambda: {"ok": True}, harness=harness,
                                     build=lambda: "a" * 40, here=lambda: [], now=T0)
        f = next(x for x in report.findings if x.key == "measures")
        assert f.status == "ok" and "tests 9 min median" in f.detail and "a cycle costs $2.50 and 30 min median over 1 runs" in f.detail
        assert report.facts["measures"]["jobs"][0]["name"] == "tests" and report.facts["measures"]["cycle"]["cost_usd"] == 2.5
        assert report.facts["devops_prs"][0]["number"] == 307
        assert [x.key for x in report.findings].index("measures") == len(report.findings) - 1  # the last row

    async def test_no_jobs_read_means_no_measures_row(self):
        async def github(repo):
            return {"main_sha": "a" * 40, "runners": [], "runs": [], "jobs_error": "rate limited"}

        report = await devops.gather(STACK, github=github, host_reader=None, claude=lambda: {"ok": True}, harness=None,
                                     build=lambda: "a" * 40, here=lambda: [], now=T0)
        assert not [x for x in report.findings if x.key == "measures"] and "measures" not in report.facts
