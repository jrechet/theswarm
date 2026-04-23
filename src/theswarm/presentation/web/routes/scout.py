"""Scout dashboard routes (Phase G).

Surfaces the intel feed, source health, and clusters — at project scope
or portfolio-wide (``project_id = ""`` / ``"_all"``).

- ``GET  /intel/feed`` — portfolio-wide intel feed fragment.
- ``GET  /projects/{pid}/intel/feed`` — project-scoped intel feed fragment.
- ``POST /intel/feed`` — ingest a new intel item (portfolio).
- ``POST /intel/items/{item_id}/action`` — mark an action on an item.
- ``POST /intel/items/{item_id}/classify`` — update category/urgency.
- ``GET  /intel/sources`` — portfolio-wide sources fragment.
- ``GET  /projects/{pid}/intel/sources`` — project-scoped sources fragment.
- ``POST /intel/sources`` — register a new source.
- ``GET  /intel/clusters`` — portfolio-wide clusters fragment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from theswarm.domain.scout.value_objects import (
    IntelCategory,
    IntelUrgency,
    SourceKind,
)
from theswarm.presentation.web.fragment_response import render_fragment_or_page

log = logging.getLogger(__name__)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


def _service(request: Request, attr: str, label: str):
    svc = getattr(request.app.state, attr, None)
    if svc is None:
        raise HTTPException(status_code=503, detail=f"{label} not configured")
    return svc


def _parse_project_ids(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


# ── Intel feed ─────────────────────────────────────────────────────


async def _render_feed(
    request: Request, project_id: str = "",
) -> HTMLResponse:
    feed_svc = _service(request, "intel_feed_service", "intel-feed service")
    items = await feed_svc.list_feed(limit=50, project_id=project_id)
    title = "Scout — Intel Feed"
    if project_id:
        title = f"Intel Feed — {project_id}"
    return render_fragment_or_page(
        request,
        "intel_feed_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "items": items,
            "categories": list(IntelCategory),
            "urgencies": list(IntelUrgency),
        },
        page_title=title,
    )


@router.get("/intel/feed", response_class=HTMLResponse)
async def portfolio_intel_feed(request: Request) -> HTMLResponse:
    return await _render_feed(request, project_id="")


@router.get("/projects/{project_id}/intel/feed", response_class=HTMLResponse)
async def project_intel_feed(
    request: Request, project_id: str,
) -> HTMLResponse:
    return await _render_feed(request, project_id=project_id)


@router.post("/intel/feed", response_class=HTMLResponse)
async def portfolio_intel_ingest(
    request: Request,
    title: str = Form(...),
    url: str = Form(...),
    source_id: str = Form(""),
    summary: str = Form(""),
    category: str = Form("fyi"),
    urgency: str = Form("normal"),
    project_ids: str = Form(""),
) -> HTMLResponse:
    feed_svc = _service(request, "intel_feed_service", "intel-feed service")
    try:
        cat_enum = IntelCategory(category)
    except ValueError:
        cat_enum = IntelCategory.FYI
    try:
        urg_enum = IntelUrgency(urgency)
    except ValueError:
        urg_enum = IntelUrgency.NORMAL
    await feed_svc.ingest(
        title=title,
        url=url,
        source_id=source_id,
        summary=summary,
        category=cat_enum,
        urgency=urg_enum,
        project_ids=_parse_project_ids(project_ids),
    )
    return await _render_feed(request, project_id="")


@router.post("/intel/items/{item_id}/action", response_class=HTMLResponse)
async def intel_mark_action(
    request: Request,
    item_id: str,
    action_taken: str = Form(...),
    project_id: str = Form(""),
) -> HTMLResponse:
    feed_svc = _service(request, "intel_feed_service", "intel-feed service")
    await feed_svc.mark_action(item_id=item_id, action_taken=action_taken)
    return await _render_feed(request, project_id=project_id)


@router.post("/intel/items/{item_id}/classify", response_class=HTMLResponse)
async def intel_classify(
    request: Request,
    item_id: str,
    category: str = Form(...),
    urgency: str = Form(""),
    project_id: str = Form(""),
) -> HTMLResponse:
    feed_svc = _service(request, "intel_feed_service", "intel-feed service")
    try:
        cat_enum = IntelCategory(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="unknown category") from exc
    urg_enum: IntelUrgency | None
    if urgency.strip():
        try:
            urg_enum = IntelUrgency(urgency)
        except ValueError:
            urg_enum = None
    else:
        urg_enum = None
    await feed_svc.classify(
        item_id=item_id, category=cat_enum, urgency=urg_enum,
    )
    return await _render_feed(request, project_id=project_id)


# ── Intel sources ──────────────────────────────────────────────────


async def _render_sources(
    request: Request, project_id: str = "",
) -> HTMLResponse:
    src_svc = _service(
        request, "intel_source_service", "intel-source service",
    )
    sources = (
        await src_svc.list_all()
        if not project_id
        else await src_svc.list_for_project(project_id)
    )
    title = "Scout — Intel Sources"
    if project_id:
        title = f"Intel Sources — {project_id}"
    return render_fragment_or_page(
        request,
        "intel_sources_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "sources": sources,
            "kinds": list(SourceKind),
        },
        page_title=title,
    )


@router.get("/intel/sources", response_class=HTMLResponse)
async def portfolio_intel_sources(request: Request) -> HTMLResponse:
    return await _render_sources(request, project_id="")


@router.get(
    "/projects/{project_id}/intel/sources", response_class=HTMLResponse,
)
async def project_intel_sources(
    request: Request, project_id: str,
) -> HTMLResponse:
    return await _render_sources(request, project_id=project_id)


@router.post("/intel/sources", response_class=HTMLResponse)
async def portfolio_intel_register_source(
    request: Request,
    name: str = Form(...),
    kind: str = Form("custom"),
    url: str = Form(""),
    project_id: str = Form(""),
) -> HTMLResponse:
    src_svc = _service(
        request, "intel_source_service", "intel-source service",
    )
    try:
        kind_enum = SourceKind(kind)
    except ValueError:
        kind_enum = SourceKind.CUSTOM
    await src_svc.register(
        name=name, kind=kind_enum, url=url, project_id=project_id,
    )
    # render portfolio view so the new source shows up
    return await _render_sources(request, project_id="")


# ── Intel clusters ─────────────────────────────────────────────────


@router.get("/intel/clusters", response_class=HTMLResponse)
async def portfolio_intel_clusters(request: Request) -> HTMLResponse:
    clus_svc = _service(
        request, "intel_cluster_service", "intel-cluster service",
    )
    clusters = await clus_svc.list_recent(limit=30)
    return render_fragment_or_page(
        request,
        "intel_clusters_fragment.html",
        {
            "request": request,
            "clusters": clusters,
        },
        page_title="Scout — Intel Clusters",
    )


@router.post("/intel/clusters", response_class=HTMLResponse)
async def portfolio_intel_create_cluster(
    request: Request,
    topic: str = Form(...),
    summary: str = Form(""),
    member_ids: str = Form(""),
) -> HTMLResponse:
    clus_svc = _service(
        request, "intel_cluster_service", "intel-cluster service",
    )
    ids = tuple(p.strip() for p in member_ids.split(",") if p.strip())
    await clus_svc.create(topic=topic, summary=summary, member_ids=ids)
    return await portfolio_intel_clusters(request)
