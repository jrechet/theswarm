"""The owner's spend view and its alerts (docs/plans/2026-10-v3-one-product.md:
"the owner's spend view gets anomaly alerts"): four ways money goes wrong,
each a pure function of the cycles' rows, and a watch that posts what is
new, once, when a cycle finishes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from theswarm.application.services import spend as sp
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import CycleCompleted, CycleFailed
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
APP, API = "jrechet/espace-client", "jrechet/theswarm"
OWNERS = {APP: ("tlphone", "TLphone"), API: ("internal", "Internal")}


def owner_of(project: str) -> tuple[str, str]:
    return OWNERS.get(project, sp.INTERNAL)


def name_of(project: str) -> str:
    return project.rsplit("/", 1)[-1]


_ids = iter(range(10_000))


def cycle(project=APP, cost=2.0, days_ago=1.0, status=CycleStatus.COMPLETED, merged=(1,), resumed="", at=NOW) -> Cycle:
    when = at - timedelta(days=days_ago)
    return Cycle(id=CycleId(f"{next(_ids):012x}"), project_id=project, status=status, triggered_by="web",
                 started_at=when, completed_at=when, total_cost_usd=cost, prs_merged=tuple(merged), resumed_as=resumed)


def usual(project=APP, n=8, cost=2.0, start=2.0):
    """n ordinary cycles before the recent ones, one a day."""
    return [cycle(project, cost, days_ago=start + i) for i in range(n)]


class TestTheView:
    def test_this_month_last_month_and_what_a_cycle_usually_costs(self):
        rows = [cycle(APP, 3.0, days_ago=1), cycle(APP, 5.0, days_ago=2), cycle(APP, 1.0, days_ago=4),
                cycle(APP, 7.0, days_ago=25), cycle(API, 2.5, days_ago=3), cycle(API, 100.0, days_ago=60)]
        got = {s.key: s for s in sp.by_customer(rows, owner_of, NOW)}
        assert got["tlphone"].this_month == 9.0 and got["tlphone"].last_month == 7.0 and got["tlphone"].cycles == 3
        assert got["tlphone"].usual == 3.0 and got["tlphone"].name == "TLphone"
        assert got["internal"].this_month == 2.5 and got["internal"].last_month == 0.0  # two months back is not read
        assert [s.key for s in sp.by_customer(rows, owner_of, NOW)] == ["tlphone", "internal"]  # the biggest first

    def test_a_running_cycle_costs_nothing_yet_and_a_fragment_is_not_a_cycle(self):
        rows = [cycle(APP, 4.0, status=CycleStatus.RUNNING), cycle(APP, 1.5, resumed="abc"), cycle(APP, 2.0)]
        [s] = sp.by_customer(rows, owner_of, NOW)
        assert s.this_month == 3.5 and s.cycles == 1 and s.usual == 2.0  # its money counts, it is not one of the cycles

    def test_an_unregistered_project_is_internal_and_a_month_boundary_is_utc(self):
        now = datetime(2026, 1, 3, 9, 0, tzinfo=timezone.utc)
        rows = [cycle("someone/else", 1.0, days_ago=1, at=now), cycle("someone/else", 6.0, days_ago=5, at=now)]
        [s] = sp.by_customer(rows, owner_of, now)
        assert s.key == "internal" and s.this_month == 1.0 and s.last_month == 6.0  # 29 Dec is last month
        assert sp.previous_month_start(now) == datetime(2025, 12, 1, tzinfo=timezone.utc)


class TestADearCycle:
    def test_three_times_the_usual_and_two_dollars_more(self):
        rows = usual() + [cycle(APP, 9.4, days_ago=0.5)]
        [a] = sp.dear_cycles(rows, NOW, name_of)
        assert a.kind == sp.DEAR and a.scope == "espace-client" and a.cost_usd == 9.4
        assert a.detail == "$9.40, against $2.00 usually (the median of its last 8)" and a.key == f"dear:{rows[-1].id}"

    def test_not_news_below_the_factor_or_the_floor_or_with_no_history(self):
        assert sp.dear_cycles(usual() + [cycle(APP, 5.9, days_ago=0.5)], NOW) == []  # under 3×
        assert sp.dear_cycles(usual(cost=0.2) + [cycle(APP, 1.5, days_ago=0.5)], NOW) == []  # 7× but only $1.30 more
        assert sp.dear_cycles(usual(n=3) + [cycle(APP, 30.0, days_ago=0.5)], NOW) == []  # nothing is usual yet

    def test_only_recent_ones_and_each_project_against_its_own(self):
        old = usual() + [cycle(APP, 9.4, days_ago=20)]
        assert sp.dear_cycles(old, NOW) == []  # older than the window the card lists
        other = usual(API, cost=8.0) + usual(APP) + [cycle(API, 9.4, days_ago=0.5)]
        assert sp.dear_cycles(other, NOW) == []  # $9.40 is ordinary on the project that usually costs $8

    def test_fragments_and_zero_cost_are_not_the_yardstick(self):
        rows = usual() + [cycle(APP, 0.1, days_ago=1.5, resumed="x"), cycle(APP, 0.0, days_ago=1.2), cycle(APP, 9.4, days_ago=0.5)]
        assert len(sp.dear_cycles(rows, NOW)) == 1


class TestABurn:
    def failed(self, cost, days_ago, **kw):
        return cycle(APP, cost, days_ago=days_ago, status=CycleStatus.FAILED, merged=(), **kw)

    def test_failed_in_a_row_with_money_spent_and_nothing_delivered(self):
        rows = usual(start=5.0) + [self.failed(1.4, 3), self.failed(1.6, 2), self.failed(1.2, 0.5)]
        [a] = sp.burn_runs(rows, NOW, name_of)
        assert a.kind == sp.BURN and a.cost_usd == pytest.approx(4.2) and a.title == "3 failed cycles in a row on espace-client"
        assert a.detail == "$4.20 spent, nothing delivered"

    def test_a_success_breaks_the_run_and_small_money_is_not_a_burn(self):
        rows = [self.failed(1.5, 4), self.failed(1.5, 3), cycle(APP, 2.0, days_ago=2), self.failed(1.5, 1)]
        assert sp.burn_runs(rows, NOW) == []
        assert sp.burn_runs([self.failed(0.4, 3), self.failed(0.5, 2), self.failed(0.6, 1)], NOW) == []  # $1.50

    def test_a_cycle_a_restart_resumed_is_a_fragment_not_a_failure(self):
        rows = [self.failed(1.5, 3, resumed="cont1"), self.failed(1.5, 2, resumed="cont2"), self.failed(1.5, 1)]
        assert sp.burn_runs(rows, NOW) == []

    def test_an_old_run_is_not_news(self):
        assert sp.burn_runs([self.failed(2.0, 30), self.failed(2.0, 29), self.failed(2.0, 28)], NOW) == []


class TestThePace:
    def test_a_month_on_course_to_cost_twice_last_month(self):
        spends = [sp.Spend("tlphone", "TLphone", this_month=40.0, last_month=20.0, cycles=5, usual=8.0)]
        [a] = sp.pace(spends, NOW)  # 19.5 days in: $40 so far, $63.59 over the 31 days, against $20
        assert a.kind == sp.PACE and a.key == "pace:2026-10:tlphone" and a.title == "TLphone is on pace to spend 3.2× last month"
        assert a.detail == "$40.00 so far this month, $63.59 at this rate, against $20.00 last month"

    def test_not_in_the_first_days_nor_against_a_small_last_month_nor_under_the_factor(self):
        assert sp.pace([sp.Spend("t", "T", 40.0, 20.0, 5, 8.0)], datetime(2026, 10, 3, tzinfo=timezone.utc)) == []
        assert sp.pace([sp.Spend("t", "T", 40.0, 4.0, 5, 8.0)], NOW) == []  # last month was pocket money
        assert sp.pace([sp.Spend("t", "T", 20.0, 20.0, 5, 4.0)], NOW) == []  # 31 projected against 20


class TestACap:
    CAPS = {APP: 50.0}

    def test_close_to_and_at_the_projects_own_cap(self):
        near = [cycle(APP, 42.0, days_ago=2)]
        [a] = sp.caps(near, self.CAPS, NOW, name_of)
        assert a.kind == sp.CAP and a.title == "espace-client is close to its monthly cap" and a.detail == "$42.00 of $50.00 (84%)"
        [full] = sp.caps([cycle(APP, 51.0, days_ago=2)], self.CAPS, NOW, name_of)
        assert full.title == "espace-client reached its monthly cap" and full.key.endswith(":full") and full.key != a.key

    def test_below_eighty_percent_no_cap_and_last_month_do_not_count(self):
        assert sp.caps([cycle(APP, 30.0, days_ago=2)], self.CAPS, NOW) == []
        assert sp.caps([cycle(APP, 90.0, days_ago=2)], {APP: 0.0}, NOW) == []
        assert sp.caps([cycle(APP, 90.0, days_ago=25)], self.CAPS, NOW) == []


class TestAllOfThem:
    def test_newest_first_and_the_chat_words(self):
        rows = usual() + [cycle(APP, 9.4, days_ago=0.5)]
        found = sp.anomalies(rows, NOW, owner_of=owner_of, name_of=name_of, caps_of={APP: 10.0})
        assert [a.kind for a in found][0] in (sp.CAP, sp.PACE) and {a.kind for a in found} >= {sp.DEAR, sp.CAP}
        dear = next(a for a in found if a.kind == sp.DEAR)
        assert sp.format_alert(dear) == "💸 **Spend alert** — A dear cycle on espace-client: $9.40, against $2.00 usually (the median of its last 8)"


class _Chat:
    def __init__(self, fail=False):
        self.posts, self.fail = [], fail

    async def post_message(self, channel, text):
        if self.fail:
            raise RuntimeError("Mattermost is down")
        self.posts.append((channel, text))


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "spend.db"))
    yield SQLiteCycleRepository(conn)
    await conn.close()


async def _lookup():
    return owner_of, name_of, {}


class TestTheRepository:
    async def test_cycles_since_a_date(self, repo):
        for c in (cycle(APP, 1.0, days_ago=3), cycle(APP, 2.0, days_ago=40), cycle(API, 3.0, days_ago=10)):
            await repo.save(c)
        got = await repo.list_since(NOW - timedelta(days=15))
        assert sorted(round(c.total_cost_usd) for c in got) == [1, 3]
        assert [c.total_cost_usd for c in got] == [1.0, 3.0]  # newest first


class TestTheWatch:
    async def _history(self, repo, rows):
        for c in rows:
            await repo.save(c)

    async def test_a_dear_cycle_is_posted_once_when_it_finishes(self, repo):
        await self._history(repo, usual())
        chat = _Chat()
        watch = sp.SpendWatch(repo, _lookup, chat=chat, channel="swarm-bots-logs", clock=lambda: NOW)
        done = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)  # the row says running at 0: the event is the truth
        await repo.save(done)
        event = CycleCompleted(cycle_id=done.id, project_id=APP, total_cost_usd=9.4, merged_prs=(7,))
        await watch.on_cycle_finished(event)
        assert len(chat.posts) == 1 and chat.posts[0][0] == "swarm-bots-logs"
        assert "A dear cycle on espace-client: $9.40, against $2.00 usually" in chat.posts[0][1]
        await watch.on_cycle_finished(event)
        assert len(chat.posts) == 1 and f"dear:{done.id}" in watch.posted  # once per alert

    async def test_a_burn_is_posted_when_the_third_failure_lands(self, repo):
        await self._history(repo, [cycle(APP, 1.5, days_ago=3, status=CycleStatus.FAILED, merged=()),
                                   cycle(APP, 1.6, days_ago=2, status=CycleStatus.FAILED, merged=())])
        chat = _Chat()
        watch = sp.SpendWatch(repo, _lookup, chat=chat, channel="c", clock=lambda: NOW)
        third = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)
        await repo.save(third)
        await watch.on_cycle_finished(CycleFailed(cycle_id=third.id, project_id=APP, error="boom", total_cost_usd=1.2))
        assert len(chat.posts) == 1 and "3 failed cycles in a row on espace-client: $4.30 spent, nothing delivered" in chat.posts[0][1]

    async def test_an_ordinary_cycle_and_another_project_s_alerts_post_nothing(self, repo):
        await self._history(repo, usual(APP) + usual(API) + [cycle(API, 9.4, days_ago=0.5)])  # API already had its dear cycle
        chat = _Chat()
        watch = sp.SpendWatch(repo, _lookup, chat=chat, channel="c", clock=lambda: NOW)
        fine = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)
        await repo.save(fine)
        await watch.on_cycle_finished(CycleCompleted(cycle_id=fine.id, project_id=APP, total_cost_usd=2.2))
        assert chat.posts == []

    async def test_no_chat_a_failing_chat_and_a_failing_repository_are_quiet(self, repo):
        await self._history(repo, usual())
        done = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)
        await repo.save(done)
        event = CycleCompleted(cycle_id=done.id, project_id=APP, total_cost_usd=9.4)
        await sp.SpendWatch(repo, _lookup, clock=lambda: NOW).on_cycle_finished(event)  # no chat configured
        broken = _Chat(fail=True)
        watch = sp.SpendWatch(repo, _lookup, chat=broken, channel="c", clock=lambda: NOW)
        await watch.on_cycle_finished(event)
        assert watch.posted == frozenset()  # not posted is not marked posted: the next finish tries again
        watch.configure_chat(_Chat(), "c")
        await watch.on_cycle_finished(event)
        assert len(watch.posted) == 1

        class Down:
            async def list_since(self, since, limit=5000):
                raise RuntimeError("database is locked")

        await sp.SpendWatch(Down(), _lookup, chat=_Chat(), channel="c").on_cycle_finished(event)


class TestTheLookups:
    async def test_a_cycle_names_its_project_by_id_or_by_repository(self):
        project = SimpleNamespace(id="jrechet-espace-client", repo=SimpleNamespace(name="espace-client", __str__=lambda s: APP),
                                  customer_id="tlphone", config=SimpleNamespace(monthly_cost_cap_usd=50.0))
        project.repo = type("R", (), {"name": "espace-client", "__str__": lambda s: APP})()
        projects = SimpleNamespace(list_all=lambda: _async([project]))
        customers = SimpleNamespace(list_all=lambda: _async([SimpleNamespace(id="tlphone", name="TLphone")]))
        owner, name, caps = await sp.lookups(projects, customers)
        assert owner("jrechet-espace-client") == owner(APP) == ("tlphone", "TLphone")
        assert name("jrechet-espace-client") == name(APP) == "espace-client" and name("x/unknown") == "unknown"
        assert owner("x/unknown") == sp.INTERNAL and caps == {"jrechet-espace-client": 50.0, APP: 50.0}


async def _async(value):
    return value


class TestTheLedger:
    async def test_a_posted_alert_is_not_posted_again_after_a_restart(self, repo, tmp_path):
        from theswarm.infrastructure.persistence.spend_alert_ledger import SQLiteSpendAlertLedger

        ledger = SQLiteSpendAlertLedger(repo._db)
        for c in usual():
            await repo.save(c)
        done = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)
        await repo.save(done)
        event = CycleCompleted(cycle_id=done.id, project_id=APP, total_cost_usd=9.4)
        first = _Chat()
        await sp.SpendWatch(repo, _lookup, chat=first, channel="c", clock=lambda: NOW, ledger=ledger).on_cycle_finished(event)
        assert len(first.posts) == 1 and await ledger.keys() == {f"dear:{done.id}"}
        after_restart = _Chat()  # a new process: an empty memory, the same ledger
        await sp.SpendWatch(repo, _lookup, chat=after_restart, channel="c", clock=lambda: NOW, ledger=ledger).on_cycle_finished(event)
        assert after_restart.posts == []

    async def test_an_alert_not_posted_is_not_written_down(self, repo):
        from theswarm.infrastructure.persistence.spend_alert_ledger import SQLiteSpendAlertLedger

        ledger = SQLiteSpendAlertLedger(repo._db)
        for c in usual():
            await repo.save(c)
        done = cycle(APP, 0.0, days_ago=0.1, status=CycleStatus.RUNNING)
        await repo.save(done)
        watch = sp.SpendWatch(repo, _lookup, chat=_Chat(fail=True), channel="c", clock=lambda: NOW, ledger=ledger)
        await watch.on_cycle_finished(CycleCompleted(cycle_id=done.id, project_id=APP, total_cost_usd=9.4))
        assert await ledger.keys() == set()
