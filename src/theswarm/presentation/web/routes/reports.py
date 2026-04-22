"""Report viewing routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse


def _sort_key(created_at: datetime) -> datetime:
    """Normalise naive datetimes to UTC so mixed-tz lists can sort."""
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/")
async def list_reports(request: Request, project_id: str = "") -> HTMLResponse:
    """List reports, optionally filtered by project."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)

    reports = []
    if report_repo is not None and project_id:
        reports = await report_repo.list_by_project(project_id, limit=20)
    elif report_repo is not None:
        # List recent reports across all projects (get from each known project)
        list_projects = request.app.state.list_projects_query
        projects = await list_projects.execute()
        for p in projects[:10]:
            reports.extend(await report_repo.list_by_project(p.id, limit=5))
        reports.sort(key=lambda r: _sort_key(r.created_at), reverse=True)
        reports = reports[:20]

    return templates.TemplateResponse(
        "reports_list.html",
        {"request": request, "reports": reports, "project_id": project_id},
    )


@router.get("/{report_id}")
async def get_report(request: Request, report_id: str) -> HTMLResponse:
    """View a single report."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)

    report = None
    if report_repo is not None:
        report = await report_repo.get(report_id)

    if report is None:
        return templates.TemplateResponse(
            "report_not_found.html",
            {"request": request, "report_id": report_id},
            status_code=404,
        )

    return templates.TemplateResponse(
        "report_detail.html",
        {"request": request, "report": report},
    )


@router.get("/api/{report_id}")
async def api_get_report(request: Request, report_id: str) -> JSONResponse:
    """JSON API: get a single report."""
    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        return JSONResponse({"error": "Reports not configured"}, status_code=501)

    report = await report_repo.get(report_id)
    if report is None:
        return JSONResponse({"error": "Not found"}, status_code=404)

    return JSONResponse({
        "id": report.id,
        "cycle_id": str(report.cycle_id),
        "project_id": report.project_id,
        "created_at": report.created_at.isoformat(),
        "summary": {
            "stories_completed": report.summary.stories_completed,
            "stories_total": report.summary.stories_total,
            "prs_merged": report.summary.prs_merged,
            "tests_passing": report.summary.tests_passing,
            "coverage_percent": report.summary.coverage_percent,
            "cost_usd": report.summary.cost_usd,
        },
        "quality_gates": [
            {"name": g.name, "status": g.status.value, "detail": g.detail}
            for g in report.quality_gates
        ],
        "stories_count": len(report.stories),
        "artifacts_count": len(report.artifacts),
    })
