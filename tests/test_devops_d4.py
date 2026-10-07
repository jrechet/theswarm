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


# ── D4b: the improvement PR ──────────────────────────────────────────────

from theswarm.agents import devops_improve as imp  # noqa: E402
from theswarm.application.services.ops_watch import OpsWatch  # noqa: E402


class _Git:
    def __init__(self, clone):
        self.clone, self.calls = clone, []

    async def clone_repo(self, url, dest):
        self.calls.append(("clone", url))
        return self.clone

    async def create_branch(self, workdir, branch, base="main"):
        self.calls.append(("branch", branch))

    async def commit_all(self, workdir, message):
        self.calls.append(("commit", message.splitlines()[0]))
        return self.committed

    async def push_branch(self, workdir, branch):
        self.calls.append(("push", branch))

    committed = True


class _Claude:
    def __init__(self, structured):
        self.structured, self.prompts = structured, []

    async def run(self, prompt, **kw):
        self.prompts.append((prompt, kw))
        return SimpleNamespace(structured=self.structured, text="")


class _GitHub:
    def __init__(self, open_prs=()):
        self.prs, self.open_prs = [], list(open_prs)

    async def get_open_prs(self):
        return self.open_prs

    async def create_pr(self, branch, base, title, body=""):
        self.prs.append({"branch": branch, "base": base, "title": title, "body": body})
        return {"number": 310, "head": branch, "base": base}  # as GitHubClient._pr_to_dict answers: no html_url


REPORT = SimpleNamespace(facts={"measures": {"jobs": [{"name": "tests", "runs": 8, "median_min": 9.0, "p90_min": 12.0, "setup_min": 0.3, "failures": 1}],
                                             "cycle": {"runs": 7, "cost_usd": 2.4, "duration_min": 41.0}}}, read_at=T0)
PROPOSED = {"status": "proposed", "title": "Cache uv downloads between CI runs", "rationale": "tests spend 2 min installing",
            "expected_gain": "tests median 9 → 7 min", "files": [{"path": ".github/workflows/ci.yml", "content": "name: CI\n# cached\n"}]}


class TestTheImprovementPR:
    def test_what_devops_may_write(self):
        assert imp.allowed_path(".github/workflows/ci.yml") and imp.allowed_path("Dockerfile") and imp.allowed_path("./docker-compose.yml")
        assert imp.allowed_path(".github/actions/write-env/action.yml") and imp.allowed_path("theswarm.yaml")
        for bad in ("src/theswarm/api.py", "tests/test_x.py", "../etc/passwd", ".github/workflows/../../x", "/etc/hosts", "", "README.md"):
            assert not imp.allowed_path(bad), bad
        assert imp.branch_name("Cache uv downloads between CI runs!", T0) == "devops/cache-uv-downloads-between-ci-runs-20261007"
        assert imp.branch_name("", T0) == "devops/improvement-20261007"
        assert imp.plain_title("ci: cache Playwright's Chromium download") == "cache Playwright's Chromium download"
        assert imp.plain_title("feat(ci)!: Cache uv") == "Cache uv" and imp.plain_title("Cache uv") == "Cache uv"

    def test_the_measures_as_words(self):
        words = imp.measures_words(REPORT.facts)
        assert words == ("- tests: 9 min median over 8 runs, p90 12, 0.3 min of it setup wait, 1 failed\n"
                         "- a cycle on the test bed: $2.40 and 41 min median over 7 runs")
        assert imp.measures_words(None) == "- nothing measured yet"

    async def test_measure_ask_branch_write_push_pr(self, tmp_path):
        clone = tmp_path / "clone"
        (clone / ".github" / "workflows").mkdir(parents=True)
        (clone / ".github" / "workflows" / "ci.yml").write_text("name: CI\n")
        (clone / "Dockerfile").write_text("FROM python\n")
        git, claude, github = _Git(str(clone)), _Claude(PROPOSED), _GitHub()
        out = await imp.propose_improvement(STACK, REPORT, claude, github, workspace_root=str(tmp_path / "ws"), git=git, now=T0)
        assert out["status"] == "opened" and out["pr"] == 310 and out["branch"] == "devops/cache-uv-downloads-between-ci-runs-20261007"
        assert (clone / ".github" / "workflows" / "ci.yml").read_text() == "name: CI\n# cached\n"
        assert git.calls == [("clone", "https://github.com/jrechet/theswarm.git"), ("branch", out["branch"]),
                             ("commit", "ci: Cache uv downloads between CI runs"), ("push", out["branch"])]
        [pr] = github.prs
        assert pr["title"] == "ci(devops): Cache uv downloads between CI runs" and pr["base"] == "main"
        assert "**Measured before**" in pr["body"] and "- tests: 9 min median over 8 runs" in pr["body"] and "tests median 9 → 7 min" in pr["body"]
        prompt, kw = claude.prompts[0]
        assert "--- .github/workflows/ci.yml\nname: CI" in prompt and "--- Dockerfile" in prompt and "- tests: 9 min median" in prompt
        assert kw["workdir"] == str(clone) and kw["output_schema"]["properties"]["files"] and kw["timeout"] == imp.IMPROVE_TIMEOUT_SECONDS

    async def test_nothing_a_refused_path_a_blank_answer_and_a_failure_are_records(self, tmp_path):
        clone = tmp_path / "clone"
        clone.mkdir()
        git, github = _Git(str(clone)), _GitHub()
        out = await imp.propose_improvement(STACK, REPORT, _Claude({"status": "nothing", "rationale": "the pipeline is already cached"}), github, git=git, now=T0)
        assert out == {"status": "nothing", "reason": "the pipeline is already cached"} and github.prs == []
        out = await imp.propose_improvement(STACK, REPORT, _Claude({**PROPOSED, "files": [{"path": "src/theswarm/api.py", "content": "x"}]}), github, git=git, now=T0)
        assert out["status"] == "failed" and "outside the pipeline: src/theswarm/api.py" in out["reason"] and github.prs == []
        out = await imp.propose_improvement(STACK, REPORT, _Claude(None), github, git=git, now=T0)
        assert out["status"] == "failed" and "no structured" in out["reason"]
        git.committed = False
        out = await imp.propose_improvement(STACK, REPORT, _Claude(PROPOSED), github, git=git, now=T0)
        assert out["status"] == "nothing" and "already has" in out["reason"] and github.prs == []

        class _Broken(_Claude):
            async def run(self, prompt, **kw):
                raise RuntimeError("quota")

        out = await imp.propose_improvement(STACK, REPORT, _Broken(None), github, git=git, now=T0)
        assert out["status"] == "failed" and out["reason"] == "RuntimeError: quota"
        assert (await imp.propose_improvement({"ci": []}, REPORT, _Claude(PROPOSED), github, git=git))["status"] == "failed"

    async def test_a_prefixed_title_a_pr_without_its_url_and_a_pr_already_open(self, tmp_path):
        clone = tmp_path / "clone"
        clone.mkdir()
        git = _Git(str(clone))
        github = _GitHub()
        out = await imp.propose_improvement(STACK, REPORT, _Claude({**PROPOSED, "title": "ci: Cache uv downloads between CI runs"}), github, git=git, now=T0)
        assert out["title"] == "Cache uv downloads between CI runs" and github.prs[0]["title"] == "ci(devops): Cache uv downloads between CI runs"
        assert out["branch"] == "devops/cache-uv-downloads-between-ci-runs-20261007" and out["url"] == "https://github.com/jrechet/theswarm/pull/310"
        again = _GitHub(open_prs=[{"number": 309, "head": "devops/cache-uv-downloads-between-ci-runs-20261007", "title": "x"}])
        out = await imp.propose_improvement(STACK, REPORT, _Claude(PROPOSED), again, git=git, now=T0)
        assert out["status"] == "opened" and out["pr"] == 309 and again.prs == [] and out["url"].endswith("/pull/309")


class TestTheWatchImproves:
    async def test_one_at_a_time_and_the_state_for_the_card(self):
        async def gather():
            return devops.OpsReport((), read_at=T0)

        watch = OpsWatch(gather, clock=lambda: T0)
        assert not watch.can_improve and (await watch.improve())["status"] == "failed"
        answers = [{"status": "opened", "pr": 310, "url": "u", "title": "t"}]

        async def improver(report):
            return answers.pop(0)

        watch.configure_improver(improver)
        assert watch.can_improve and watch.improvement is None
        task = watch.start_improvement()
        assert watch.pending_improvement is task
        assert await task == {"status": "opened", "pr": 310, "url": "u", "title": "t", "at": T0.isoformat()}
        assert watch.improvement["pr"] == 310 and watch.pending_improvement is None

        async def broken(report):
            raise RuntimeError("no Claude")

        watch.configure_improver(broken)
        assert (await watch.improve())["status"] == "failed" and "no Claude" in watch.improvement["reason"]
