"""The owner's spend view, and its alerts (V3 plan: "the owner's spend view
gets anomaly alerts").

Spend is a sum over the cycles' rows (`cycles.total_cost_usd`) — no new
table. Customers never see it. This module is two things:

- **The view**: this month and last month per customer, how many cycles,
  what a cycle usually costs (`by_customer`).
- **The alerts** — four ways money goes wrong, each a pure function of the
  rows so the card and the chat read the same truth:
  - **dear** — one cycle cost `DEAR_FACTOR` times what the project's last
    `PRIOR_CYCLES` usually cost, and at least `DEAR_FLOOR_USD` more (a
    twenty-cent job that cost eighty cents is not news);
  - **burn** — `BURN_RUN` cycles failed in a row on a project, nothing
    delivered, `BURN_MIN_USD` or more spent: money gone with nothing to
    show (a row a restart interrupted and a continuation resumed is a
    fragment, never counted);
  - **pace** — this month, at today's rate, will cost `PACE_FACTOR` times
    last month (only once last month was real money and the month is
    `PACE_MIN_DAYS` days old);
  - **cap** — a project's month reached `CAP_WARN` of its own
    `monthly_cost_cap_usd`.

`SpendWatch` evaluates the same detectors when a cycle finishes
(`CycleCompleted`, `CycleFailed`) and posts what is new on the PO's
channel, once per alert key — the keys kept in a ledger (v038), so a
restart does not post an alert twice.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

log = logging.getLogger(__name__)

DEAR_FACTOR = 3.0
DEAR_FLOOR_USD = 2.0
PRIOR_CYCLES = 8  # the cycles before one that make "usual"
PRIOR_MIN = 4  # fewer than this and nothing is usual yet
BURN_RUN = 3
BURN_MIN_USD = 3.0
PACE_FACTOR = 2.0
PACE_MIN_LAST_MONTH_USD = 5.0
PACE_MIN_DAYS = 5.0
CAP_WARN = 0.8
RECENT_DAYS = 14  # the alerts the card lists

DEAR, BURN, PACE, CAP = "dear", "burn", "pace", "cap"
FINISHED = (CycleStatus.COMPLETED, CycleStatus.FAILED)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def month_start(now: datetime) -> datetime:
    now = _utc(now)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def previous_month_start(now: datetime) -> datetime:
    return month_start(month_start(now) - timedelta(days=1))


def _days_in_month(start: datetime) -> int:
    nxt = (start + timedelta(days=32)).replace(day=1)
    return (nxt - start).days


def _cost(c: Cycle) -> float:
    return float(c.total_cost_usd or 0.0)


def _when(c: Cycle) -> datetime | None:
    return _utc(c.completed_at or c.started_at)


def _fragment(c: Cycle) -> bool:
    """A row a restart interrupted and a continuation resumed: its money is
    counted in the total, but it is not a cycle to judge or to compare with."""
    return bool(c.resumed_as)


def usd(value: float) -> str:
    return f"${value:,.2f}"


@dataclass(frozen=True)
class Spend:
    """What one customer (or project) spent."""

    key: str
    name: str
    this_month: float
    last_month: float
    cycles: int  # finished this month
    usual: float | None  # the median finished cycle this month

    def as_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "this_month": round(self.this_month, 2),
                "last_month": round(self.last_month, 2), "cycles": self.cycles,
                "usual": None if self.usual is None else round(self.usual, 2)}


@dataclass(frozen=True)
class Anomaly:
    key: str  # stable: the same alert is the same key, so chat posts it once
    kind: str
    scope: str  # what it is about: a project's name, a customer's name
    title: str
    detail: str
    at: datetime
    cost_usd: float = 0.0
    cycle_id: str = ""
    project: str = ""  # the project as the cycles name it; empty for a customer's pace

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "scope": self.scope, "title": self.title,
                "detail": self.detail, "at": self.at.isoformat(), "cost_usd": round(self.cost_usd, 2),
                "cycle_id": self.cycle_id}


# ── The view ─────────────────────────────────────────────────────────


def by_customer(cycles: list[Cycle], owner_of: Callable[[str], tuple[str, str]], now: datetime) -> list[Spend]:
    """This month and last month per customer; `owner_of(project_id)` is (customer id, name)."""
    this_start, last_start = month_start(now), previous_month_start(now)
    this: dict[str, float] = {}
    last: dict[str, float] = {}
    costs: dict[str, list[float]] = {}
    names: dict[str, str] = {}
    for c in cycles:
        when = _when(c)
        if when is None or c.status not in FINISHED + (CycleStatus.CANCELLED,):
            continue
        key, name = owner_of(c.project_id)
        names[key] = name
        if when >= this_start:
            this[key] = this.get(key, 0.0) + _cost(c)
            if c.status in FINISHED and not _fragment(c) and _cost(c) > 0:
                costs.setdefault(key, []).append(_cost(c))
        elif when >= last_start:
            last[key] = last.get(key, 0.0) + _cost(c)
    out = [Spend(key=k, name=names[k], this_month=this.get(k, 0.0), last_month=last.get(k, 0.0),
                 cycles=len(costs.get(k, [])), usual=statistics.median(costs[k]) if costs.get(k) else None)
           for k in names]
    return sorted(out, key=lambda s: (-s.this_month, -s.last_month, s.name))


# ── The alerts ───────────────────────────────────────────────────────


def dear_cycles(cycles: list[Cycle], now: datetime, name_of: Callable[[str], str] = lambda p: p) -> list[Anomaly]:
    """Cycles of the last `RECENT_DAYS` that cost far more than their project usually does."""
    since = _utc(now) - timedelta(days=RECENT_DAYS)
    by_project: dict[str, list[Cycle]] = {}
    for c in cycles:
        if c.status in FINISHED and not _fragment(c) and _cost(c) > 0 and _when(c) is not None:
            by_project.setdefault(c.project_id, []).append(c)
    out = []
    for project, rows in by_project.items():
        rows.sort(key=lambda c: _when(c))
        for i, c in enumerate(rows):
            if _when(c) < since:
                continue
            prior = [_cost(p) for p in rows[max(0, i - PRIOR_CYCLES):i]]
            if len(prior) < PRIOR_MIN:
                continue
            usual = statistics.median(prior)
            if _cost(c) >= DEAR_FACTOR * usual and _cost(c) - usual >= DEAR_FLOOR_USD:
                scope = name_of(project)
                out.append(Anomaly(
                    key=f"dear:{c.id}", kind=DEAR, scope=scope, at=_when(c), cost_usd=_cost(c), cycle_id=str(c.id), project=project,
                    title=f"A dear cycle on {scope}",
                    detail=f"{usd(_cost(c))}, against {usd(usual)} usually (the median of its last {len(prior)})",
                ))
    return out


def burn_runs(cycles: list[Cycle], now: datetime, name_of: Callable[[str], str] = lambda p: p) -> list[Anomaly]:
    """Projects whose newest cycles failed in a row, spent real money and delivered nothing."""
    since = _utc(now) - timedelta(days=RECENT_DAYS)
    by_project: dict[str, list[Cycle]] = {}
    for c in cycles:
        if c.status in FINISHED and not _fragment(c) and _when(c) is not None:
            by_project.setdefault(c.project_id, []).append(c)
    out = []
    for project, rows in by_project.items():
        rows.sort(key=lambda c: _when(c), reverse=True)  # newest first
        run: list[Cycle] = []
        for c in rows:
            if c.status == CycleStatus.FAILED and not c.prs_merged:
                run.append(c)
            else:
                break
        spent = sum(_cost(c) for c in run)
        if len(run) >= BURN_RUN and spent >= BURN_MIN_USD and _when(run[0]) >= since:
            scope = name_of(project)
            out.append(Anomaly(
                key=f"burn:{project}:{run[0].id}", kind=BURN, scope=scope, at=_when(run[0]), cost_usd=spent,
                cycle_id=str(run[0].id), project=project, title=f"{len(run)} failed cycles in a row on {scope}",
                detail=f"{usd(spent)} spent, nothing delivered",
            ))
    return out


def pace(spends: list[Spend], now: datetime) -> list[Anomaly]:
    """Customers whose month, at today's rate, will cost far more than last month did."""
    now = _utc(now)
    start = month_start(now)
    elapsed = (now - start).total_seconds() / 86400
    if elapsed < PACE_MIN_DAYS:
        return []
    out = []
    for s in spends:
        if s.last_month < PACE_MIN_LAST_MONTH_USD:
            continue
        projected = s.this_month / elapsed * _days_in_month(start)
        if projected >= PACE_FACTOR * s.last_month:
            out.append(Anomaly(
                key=f"pace:{start:%Y-%m}:{s.key}", kind=PACE, scope=s.name, at=now, cost_usd=s.this_month,
                title=f"{s.name} is on pace to spend {projected / s.last_month:.1f}× last month",
                detail=f"{usd(s.this_month)} so far this month, {usd(projected)} at this rate, against {usd(s.last_month)} last month",
            ))
    return out


def caps(cycles: list[Cycle], caps_of: dict[str, float], now: datetime,
         name_of: Callable[[str], str] = lambda p: p) -> list[Anomaly]:
    """Projects whose month reached `CAP_WARN` of their own monthly cap (`caps_of`: project id → cap)."""
    now = _utc(now)
    start = month_start(now)
    spent: dict[str, float] = {}
    for c in cycles:
        when = _when(c)
        if when is not None and when >= start:
            spent[c.project_id] = spent.get(c.project_id, 0.0) + _cost(c)
    out = []
    for project, cap in caps_of.items():
        if cap <= 0 or spent.get(project, 0.0) < CAP_WARN * cap:
            continue
        used = spent[project]
        scope = name_of(project)
        out.append(Anomaly(
            key=f"cap:{start:%Y-%m}:{project}:{'full' if used >= cap else 'near'}", kind=CAP, scope=scope, at=now, cost_usd=used, project=project,
            title=f"{scope} {'reached' if used >= cap else 'is close to'} its monthly cap",
            detail=f"{usd(used)} of {usd(cap)} ({used / cap:.0%})",
        ))
    return out


def anomalies(cycles: list[Cycle], now: datetime, *, owner_of: Callable[[str], tuple[str, str]],
              name_of: Callable[[str], str] = lambda p: p, caps_of: dict[str, float] | None = None) -> list[Anomaly]:
    """Every alert the rows hold, newest first."""
    found = (dear_cycles(cycles, now, name_of) + burn_runs(cycles, now, name_of)
             + pace(by_customer(cycles, owner_of, now), now) + caps(cycles, caps_of or {}, now, name_of))
    return sorted(found, key=lambda a: a.at, reverse=True)


# ── Who owns what, and the view the card and the API draw ────────────

Lookups = tuple[Callable[[str], tuple[str, str]], Callable[[str], str], dict[str, float]]
INTERNAL = ("internal", "Internal")


async def lookups(project_repo: Any, customer_repo: Any) -> Lookups:
    """(owner_of, name_of, caps_of) from the registry: a cycle names its project by its
    registered id or by the repository's full name, both are mapped."""
    names = {c.id: c.name for c in await customer_repo.list_all()}
    owners: dict[str, tuple[str, str]] = {}
    shown: dict[str, str] = {}
    caps_of: dict[str, float] = {}
    for p in await project_repo.list_all():
        who = (p.customer_id, names.get(p.customer_id, p.customer_id))
        cap = float(getattr(p.config, "monthly_cost_cap_usd", 0.0) or 0.0)
        for key in {p.id, str(p.repo)}:
            owners[key] = who
            shown[key] = p.repo.name
            if cap > 0:
                caps_of[key] = cap

    def owner_of(project_id: str) -> tuple[str, str]:
        return owners.get(project_id, INTERNAL)

    def name_of(project_id: str) -> str:
        return shown.get(project_id) or project_id.rsplit("/", 1)[-1]

    return owner_of, name_of, caps_of


@dataclass(frozen=True)
class SpendView:
    month: str
    last_month: str
    customers: tuple[Spend, ...]
    anomalies: tuple[Anomaly, ...]

    @property
    def total(self) -> float:
        return sum(s.this_month for s in self.customers)

    @property
    def total_last(self) -> float:
        return sum(s.last_month for s in self.customers)

    def as_dict(self) -> dict:
        return {"month": self.month, "last_month": self.last_month, "total": round(self.total, 2),
                "total_last": round(self.total_last, 2), "customers": [s.as_dict() for s in self.customers],
                "anomalies": [a.as_dict() for a in self.anomalies]}


async def spend_view(cycle_repo: Any, project_repo: Any, customer_repo: Any, now: datetime | None = None) -> SpendView:
    """This month and last, per customer, and every alert the rows hold."""
    now = _utc(now) if now else datetime.now(timezone.utc)
    owner_of, name_of, caps_of = await lookups(project_repo, customer_repo)
    rows = await cycle_repo.list_since(previous_month_start(now))
    return SpendView(
        month=f"{month_start(now):%B %Y}", last_month=f"{previous_month_start(now):%B}",
        customers=tuple(by_customer(rows, owner_of, now)),
        anomalies=tuple(a for a in anomalies(rows, now, owner_of=owner_of, name_of=name_of, caps_of=caps_of)
                        if a.kind in (PACE, CAP) or a.at >= now - timedelta(days=RECENT_DAYS)),
    )


# ── The chat ─────────────────────────────────────────────────────────

ICONS = {DEAR: "💸", BURN: "🔥", PACE: "📈", CAP: "🚧"}


def format_alert(a: Anomaly) -> str:
    return f"{ICONS.get(a.kind, '💸')} **Spend alert** — {a.title}: {a.detail}"


class SpendWatch:
    """When a cycle finishes, evaluates the alerts and posts what is new, once per key."""

    def __init__(self, cycle_repo: Any, lookup: Callable[[], Awaitable[Lookups]], *, chat: Any = None, channel: str = "",
                 clock: Callable[[], datetime] | None = None, ledger: Any = None) -> None:
        self._cycles = cycle_repo
        self._lookup = lookup
        self._ledger = ledger  # the keys already posted, kept across restarts
        self._ledger_read = ledger is None
        self._chat = chat
        self._channel = channel
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._posted: set[str] = set()

    def configure_chat(self, chat: Any, channel: str) -> None:
        self._chat, self._channel = chat, channel

    @property
    def posted(self) -> frozenset[str]:
        return frozenset(self._posted)

    async def on_cycle_finished(self, event: Any) -> None:
        """Subscribed to `CycleCompleted` and `CycleFailed`; never the cycle's problem."""
        try:
            await self._evaluate(event)
        except Exception:  # noqa: BLE001
            log.exception("SpendWatch: the alerts were not evaluated")

    async def _evaluate(self, event: Any) -> None:
        if self._chat is None or not self._channel:
            return
        if not self._ledger_read:
            self._posted |= await self._ledger.keys()
            self._ledger_read = True
        now = self._clock()
        cycle_id = str(getattr(event, "cycle_id", ""))
        project_id = getattr(event, "project_id", "") or ""
        failed = type(event).__name__ == "CycleFailed"
        since = previous_month_start(now)
        rows = [c for c in await self._cycles.list_since(since) if str(c.id) != cycle_id]
        stored = await self._cycles.get(CycleId(cycle_id)) if cycle_id else None
        # The row may not hold the final cost yet (the persistence handler runs beside this one):
        # the event is the truth for the cycle that just finished.
        rows.append(Cycle(
            id=CycleId(cycle_id) if cycle_id else CycleId.generate(), project_id=project_id,
            status=CycleStatus.FAILED if failed else CycleStatus.COMPLETED, triggered_by="",
            started_at=_utc(stored.started_at) if stored and stored.started_at else now, completed_at=now,
            total_cost_usd=float(getattr(event, "total_cost_usd", 0.0) or 0.0),
            prs_merged=tuple(getattr(event, "merged_prs", ()) or ()), resumed_as=stored.resumed_as if stored else "",
        ))
        owner_of, name_of, caps_of = await self._lookup()
        customer = owner_of(project_id)[1]
        for a in anomalies(rows, now, owner_of=owner_of, name_of=name_of, caps_of=caps_of):
            # what this finish caused: its own cycle's alert, its project's, or its customer's pace
            if a.cycle_id == cycle_id or a.project == project_id or (a.kind == PACE and a.scope == customer):
                await self._post(a)

    async def _post(self, a: Anomaly) -> None:
        if a.key in self._posted:
            return
        self._posted.add(a.key)
        try:
            await self._chat.post_message(self._channel, format_alert(a))
        except Exception:  # noqa: BLE001 — not posted is not lost: the card shows it
            self._posted.discard(a.key)
            log.exception("SpendWatch: the alert could not be posted")
            return
        if self._ledger is not None:
            try:
                await self._ledger.add(a.key)
            except Exception:  # noqa: BLE001 — posted is what matters; a restart may repeat this one
                log.exception("SpendWatch: the posted alert could not be written down")
