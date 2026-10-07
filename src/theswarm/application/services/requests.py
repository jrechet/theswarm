"""Requests — the one thing a customer writes (V3 M5).

A member submits a need in their own words; it lands in the owner's inbox.
The owner turns it into a feature — a GitHub issue on one of the
customer's projects — or declines it. From there the request follows the
feature: a cycle started on the issue makes it *building*, that cycle's
demo makes it *delivered* (`RequestTracker`, on the event bus).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from theswarm.domain.customers.entities import Customer
from theswarm.domain.customers.ports import RequestRepository
from theswarm.domain.customers.requests import TITLE_MAX, Request
from theswarm.domain.projects.entities import Project

log = logging.getLogger(__name__)

REQUEST_MARKER = "<!-- swarm:request {id} -->"


class RequestError(ValueError):
    """A request that cannot be honoured, with the reason."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def feature_body(request: Request, customer: Customer) -> str:
    """The GitHub issue's body: the customer's words, who asked, the marker."""
    who = f"{request.author_name} ({customer.name})" if request.author_name else customer.name
    parts = [request.body.strip()] if request.body.strip() else []
    parts.append(f"Requested by {who}, {request.created_at.strftime('%d %b %Y')}.")
    parts.append(REQUEST_MARKER.format(id=request.id))
    return "\n\n".join(parts)


class RequestService:
    def __init__(self, requests: RequestRepository, projects=None) -> None:
        self._requests = requests
        self._projects = projects

    # ── A member writes ──────────────────────────────────────────────

    async def submit(self, customer: Customer, title: str, body: str = "", *,
                     member_id: str = "", author_name: str = "", project: Project | None = None,
                     now: datetime | None = None) -> Request:
        title = " ".join(title.split())
        if not title:
            raise RequestError("Say what you need in one line.")
        now = now or _now()
        request = Request(
            id=uuid.uuid4().hex[:12], customer_id=customer.id, title=title[:TITLE_MAX],
            body=body.strip(), project_id=project.id if project is not None else "",
            member_id=member_id, author_name=author_name.strip(), created_at=now, updated_at=now,
        )
        await self._requests.save(request)
        log.info("Request %s received from %s (%s)", request.id, author_name or member_id or "a member", customer.slug)
        return request

    # ── The owner decides ────────────────────────────────────────────

    async def plan(self, request: Request, customer: Customer, project: Project, *,
                   title: str | None = None, body: str | None = None, github=None,
                   now: datetime | None = None) -> Request:
        """Turn a request into a feature: the issue on the project, the request planned."""
        if request.status != "received":
            raise RequestError("Only a received request can be planned.")
        issue_title = " ".join((title or request.title).split())[:TITLE_MAX] or request.title
        issue_body = body if body is not None else feature_body(request, customer)
        if github is None:
            from theswarm.tools.github import GitHubClient

            github = GitHubClient(str(project.repo))
        created = await github.create_issue(title=issue_title, body=issue_body, labels=["status:backlog"])
        number = created.get("number") if isinstance(created, dict) else None
        if not isinstance(number, int):
            raise RequestError("GitHub did not give the issue a number.")
        planned = request.planned(str(project.repo), number, project_id=project.id, now=now)
        await self._requests.save(planned)
        log.info("Request %s planned as %s#%d", request.id, project.repo, number)
        return planned

    async def decline(self, request: Request, reason: str = "", now: datetime | None = None) -> Request:
        declined = request.declined(reason, now=now)
        await self._requests.save(declined)
        return declined

    # ── The feature's life reaches the request ───────────────────────

    async def on_cycle_started(self, repo: str, issue_number: int | None, now: datetime | None = None) -> int:
        if not repo or issue_number is None:
            return 0
        changed = 0
        for request in await self._requests.list_by_feature(repo, issue_number):
            moved = request.building(now=now)
            if moved is not request:
                await self._requests.save(moved)
                changed += 1
        return changed

    async def on_demo_ready(self, repo: str, issue_number: int | None, report_id: str,
                            now: datetime | None = None) -> int:
        if not repo or issue_number is None:
            return 0
        changed = 0
        for request in await self._requests.list_by_feature(repo, issue_number):
            moved = request.delivered(report_id, now=now)
            if moved is not request:
                await self._requests.save(moved)
                changed += 1
        return changed

    # ── Reading ──────────────────────────────────────────────────────

    async def get(self, request_id: str) -> Request | None:
        return await self._requests.get(request_id)

    async def inbox(self, limit: int = 50) -> list[Request]:
        return await self._requests.list_inbox(limit)

    async def open_requests(self, limit: int = 200) -> list[Request]:
        return await self._requests.list_open(limit)

    async def for_customer(self, customer: Customer, limit: int = 50) -> list[Request]:
        return await self._requests.list_for_customer(customer.id, limit)


class RequestTracker:
    """Follows the swarm's events so a request moves with its feature.

    `CycleStarted` names the pinned issue; `DemoReady` names it too. Both
    name the project the way the cycle does — the repository's full name,
    or a registered id the project repository resolves.
    """

    def __init__(self, service: RequestService, projects=None) -> None:
        self._service = service
        self._projects = projects

    async def _repo_of(self, project_id: str) -> str:
        if "/" in project_id or self._projects is None:
            return project_id
        try:
            project = await self._projects.get(project_id)
        except Exception:  # noqa: BLE001
            return project_id
        return str(project.repo) if project is not None else project_id

    async def on_cycle_started(self, event) -> None:
        try:
            repo = await self._repo_of(getattr(event, "project_id", "") or "")
            await self._service.on_cycle_started(repo, getattr(event, "issue_number", None))
        except Exception:  # noqa: BLE001 — never the cycle's problem
            log.exception("RequestTracker: CycleStarted not followed")

    async def on_demo_ready(self, event) -> None:
        try:
            repo = await self._repo_of(getattr(event, "project_id", "") or "")
            await self._service.on_demo_ready(repo, getattr(event, "issue_number", None),
                                              getattr(event, "report_id", "") or "")
        except Exception:  # noqa: BLE001
            log.exception("RequestTracker: DemoReady not followed")
