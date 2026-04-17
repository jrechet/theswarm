"""Demo playback routes — browse and play cycle demos."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/demos", tags=["demos"])


def _parse_since(since: str | None) -> datetime | None:
    """Parse ``YYYY-MM-DD`` into a timezone-aware UTC datetime, or None."""
    if not since:
        return None
    try:
        return datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@router.get("/")
async def browse_demos(
    request: Request,
    project: str | None = Query(default=None, description="Filter by project ID"),
    since: str | None = Query(default=None, description="Filter demos on/after YYYY-MM-DD"),
) -> HTMLResponse:
    """Browse all demos grouped by project, optionally filtered."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)
    list_projects = request.app.state.list_projects_query

    projects = await list_projects.execute()
    since_dt = _parse_since(since)

    demos_by_project: dict[str, list] = {}
    if report_repo is not None:
        target_ids = [project] if project else [p.id for p in projects]
        for pid in target_ids:
            reports = await report_repo.list_by_project(pid, limit=50)
            if since_dt is not None:
                reports = [r for r in reports if r.created_at >= since_dt]
            if reports:
                demos_by_project[pid] = reports

        if project is None:
            # Also surface reports for unregistered projects
            all_recent = await report_repo.list_recent(limit=100)
            known_ids = {p.id for p in projects}
            for r in all_recent:
                if r.project_id in known_ids:
                    continue
                if since_dt is not None and r.created_at < since_dt:
                    continue
                demos_by_project.setdefault(r.project_id, []).append(r)

    return templates.TemplateResponse(
        "demos_browse.html",
        {
            "request": request,
            "projects": projects,
            "demos_by_project": demos_by_project,
            "total_demos": sum(len(v) for v in demos_by_project.values()),
            "active_project": project or "",
            "active_since": since or "",
        },
    )


@router.get("/{report_id}/play")
async def play_demo(request: Request, report_id: str) -> HTMLResponse:
    """Full-screen demo player for a single report."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)

    report = None
    if report_repo is not None:
        report = await report_repo.get(report_id)

    if report is None:
        return templates.TemplateResponse(
            "demo_not_found.html",
            {"request": request, "report_id": report_id},
            status_code=404,
        )

    # Build ordered slide data for the player
    slides = _build_slides(report)

    # Get adjacent demos for prev/next navigation
    prev_demo = None
    next_demo = None
    if report_repo is not None:
        project_reports = await report_repo.list_by_project(
            report.project_id, limit=50,
        )
        for i, r in enumerate(project_reports):
            if r.id == report_id:
                if i > 0:
                    next_demo = project_reports[i - 1]  # newer
                if i < len(project_reports) - 1:
                    prev_demo = project_reports[i + 1]  # older
                break

    return templates.TemplateResponse(
        "demo_player.html",
        {
            "request": request,
            "report": report,
            "slides": slides,
            "slide_count": len(slides),
            "prev_demo": prev_demo,
            "next_demo": next_demo,
        },
    )


def _build_slides(report) -> list[dict]:
    """Build an ordered list of slide descriptors from a DemoReport."""
    slides: list[dict] = []

    # Slide 0: Title
    slides.append({
        "type": "title",
        "project": report.project_id,
        "date": report.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        "summary": report.summary,
        "gates_pass": report.all_gates_pass,
    })

    # Per-story slides
    for i, story in enumerate(report.stories):
        slides.append({
            "type": "story",
            "index": i,
            "story": story,
        })

        # Before/after comparison slide if screenshots exist
        if story.screenshots_before or story.screenshots_after:
            slides.append({
                "type": "screenshots",
                "index": i,
                "story": story,
            })

        # Video slide
        if story.video:
            slides.append({
                "type": "video",
                "index": i,
                "story": story,
            })

    # Quality gates slide
    if report.quality_gates:
        slides.append({
            "type": "quality_gates",
            "gates": report.quality_gates,
        })

    # Demo screenshots (top-level artifacts)
    screenshots = [a for a in report.artifacts if a.type.value == "screenshot"]
    if screenshots:
        slides.append({
            "type": "gallery",
            "artifacts": screenshots,
        })

    # Videos (top-level artifacts)
    videos = [a for a in report.artifacts if a.type.value == "video"]
    for v in videos:
        slides.append({
            "type": "artifact_video",
            "artifact": v,
        })

    # Agent learnings
    if report.agent_learnings:
        slides.append({
            "type": "learnings",
            "learnings": report.agent_learnings,
        })

    return slides
