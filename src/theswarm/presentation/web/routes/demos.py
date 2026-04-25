"""Demo playback routes — browse and play cycle demos."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from theswarm.domain.reporting.events import (
    StoryApproved,
    StoryCommented,
    StoryRejected,
)

router = APIRouter(prefix="/demos", tags=["demos"])
public_router = APIRouter(tags=["demos-public"])


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

    # When filtered by a specific project that has no demos, surface its
    # recent cycle attempts (any status) so the empty state answers
    # "we tried — here's what happened" rather than just saying nothing.
    recent_attempts: list = []
    if project and not demos_by_project:
        cycle_repo = getattr(request.app.state, "cycle_repo", None)
        if cycle_repo is not None:
            try:
                recent_attempts = await cycle_repo.list_by_project(project, limit=10)
            except Exception:
                recent_attempts = []

    return templates.TemplateResponse(
        "demos_browse.html",
        {
            "request": request,
            "projects": projects,
            "demos_by_project": demos_by_project,
            "total_demos": sum(len(v) for v in demos_by_project.values()),
            "active_project": project or "",
            "active_since": since or "",
            "recent_attempts": recent_attempts,
        },
    )


async def _render_player(
    request: Request,
    report,
    *,
    is_public: bool,
) -> HTMLResponse:
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)
    slides = _build_slides(report)

    prev_demo = None
    next_demo = None
    if report_repo is not None and not is_public:
        project_reports = await report_repo.list_by_project(
            report.project_id, limit=50,
        )
        for i, r in enumerate(project_reports):
            if r.id == report.id:
                if i > 0:
                    next_demo = project_reports[i - 1]
                if i < len(project_reports) - 1:
                    prev_demo = project_reports[i + 1]
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
            "is_public": is_public,
        },
    )


@router.get("/compare")
async def compare_demos(
    request: Request,
    a: str = Query(..., description="Report ID for panel A"),
    b: str = Query(..., description="Report ID for panel B"),
) -> HTMLResponse:
    """A/B comparator — two demos side-by-side with synced playback."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)

    if report_repo is None:
        return templates.TemplateResponse(
            "demo_not_found.html",
            {"request": request, "report_id": f"{a} vs {b}"},
            status_code=404,
        )

    report_a = await report_repo.get(a)
    report_b = await report_repo.get(b)

    if report_a is None or report_b is None:
        missing = a if report_a is None else b
        return templates.TemplateResponse(
            "demo_not_found.html",
            {"request": request, "report_id": missing},
            status_code=404,
        )

    return templates.TemplateResponse(
        "demos_compare.html",
        {
            "request": request,
            "report_a": report_a,
            "report_b": report_b,
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

    return await _render_player(request, report, is_public=False)


@public_router.get("/d/{short}")
async def play_public_demo(request: Request, short: str) -> HTMLResponse:
    """Read-only public demo player resolved by short slug."""
    templates = request.app.state.templates
    report_repo = getattr(request.app.state, "report_repo", None)

    match = None
    if report_repo is not None:
        short_norm = short.lower()
        recent = await report_repo.list_recent(limit=500)
        for r in recent:
            if r.public_slug == short_norm:
                match = r
                break

    if match is None:
        return templates.TemplateResponse(
            "demo_not_found.html",
            {"request": request, "report_id": short},
            status_code=404,
        )

    return await _render_player(request, match, is_public=True)


async def _resolve_story_pr(report_repo, report_id: str, ticket_id: str):
    """Return (report, story) or raise HTTPException(404)."""
    report = await report_repo.get(report_id) if report_repo is not None else None
    if report is None:
        raise HTTPException(status_code=404, detail="report not found")
    story = next((s for s in report.stories if s.ticket_id == ticket_id), None)
    if story is None:
        raise HTTPException(status_code=404, detail="story not found")
    return report, story


async def _record_action(db, report_id: str, ticket_id: str, action: str, actor: str) -> None:
    """Insert a row into story_actions; raise HTTPException(409) if already recorded."""
    if db is None:
        return
    cursor = await db.execute(
        "SELECT 1 FROM story_actions WHERE report_id = ? AND ticket_id = ? AND action = ?",
        (report_id, ticket_id, action),
    )
    row = await cursor.fetchone()
    if row:
        raise HTTPException(status_code=409, detail=f"already {action}d")
    await db.execute(
        "INSERT INTO story_actions (report_id, ticket_id, action, actor, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (report_id, ticket_id, action, actor, datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()


def _resolve_vcs(request: Request, report):
    factory = getattr(request.app.state, "vcs_factory", None)
    if factory is None:
        return None
    project_repo = getattr(request.app.state, "project_repo", None)
    return factory, project_repo


@router.post("/{report_id}/stories/{ticket_id}/approve")
async def approve_story(
    request: Request,
    report_id: str,
    ticket_id: str,
    actor: str = Form(default="dashboard-user"),
) -> JSONResponse:
    report_repo = getattr(request.app.state, "report_repo", None)
    db = getattr(request.app.state, "db", None)
    event_bus = getattr(request.app.state, "event_bus", None)
    report, story = await _resolve_story_pr(report_repo, report_id, ticket_id)

    await _record_action(db, report_id, ticket_id, "approve", actor)

    if story.pr_number:
        factory = getattr(request.app.state, "vcs_factory", None)
        project_repo = getattr(request.app.state, "project_repo", None)
        if factory is not None and project_repo is not None:
            project = await project_repo.get(report.project_id)
            if project is not None:
                vcs = factory(str(project.repo))
                await vcs.submit_review(story.pr_number, f"Approved by {actor}", "APPROVE")
                await vcs.merge_pr(story.pr_number)

    if event_bus is not None:
        await event_bus.publish(
            StoryApproved(report_id=report_id, ticket_id=ticket_id, user=actor),
        )

    return JSONResponse({"ok": True, "action": "approve"})


@router.post("/{report_id}/stories/{ticket_id}/reject")
async def reject_story(
    request: Request,
    report_id: str,
    ticket_id: str,
    actor: str = Form(default="dashboard-user"),
    comment: str = Form(default=""),
) -> JSONResponse:
    report_repo = getattr(request.app.state, "report_repo", None)
    db = getattr(request.app.state, "db", None)
    event_bus = getattr(request.app.state, "event_bus", None)
    report, story = await _resolve_story_pr(report_repo, report_id, ticket_id)

    await _record_action(db, report_id, ticket_id, "reject", actor)

    if story.pr_number:
        factory = getattr(request.app.state, "vcs_factory", None)
        project_repo = getattr(request.app.state, "project_repo", None)
        if factory is not None and project_repo is not None:
            project = await project_repo.get(report.project_id)
            if project is not None:
                vcs = factory(str(project.repo))
                body = comment or f"Rejected by {actor}"
                await vcs.submit_review(story.pr_number, body, "REQUEST_CHANGES")
                if hasattr(vcs, "close_pr"):
                    await vcs.close_pr(story.pr_number)

    if event_bus is not None:
        await event_bus.publish(
            StoryRejected(
                report_id=report_id, ticket_id=ticket_id, user=actor, comment=comment,
            ),
        )

    return JSONResponse({"ok": True, "action": "reject"})


@router.post("/{report_id}/stories/{ticket_id}/comment")
async def comment_story(
    request: Request,
    report_id: str,
    ticket_id: str,
    actor: str = Form(default="dashboard-user"),
    comment: str = Form(default=""),
) -> JSONResponse:
    if not comment.strip():
        raise HTTPException(status_code=400, detail="comment required")

    report_repo = getattr(request.app.state, "report_repo", None)
    event_bus = getattr(request.app.state, "event_bus", None)
    report, story = await _resolve_story_pr(report_repo, report_id, ticket_id)

    if story.pr_number:
        factory = getattr(request.app.state, "vcs_factory", None)
        project_repo = getattr(request.app.state, "project_repo", None)
        if factory is not None and project_repo is not None:
            project = await project_repo.get(report.project_id)
            if project is not None:
                vcs = factory(str(project.repo))
                if hasattr(vcs, "create_pr_comment"):
                    await vcs.create_pr_comment(story.pr_number, f"**{actor}:** {comment}")
                else:
                    await vcs.submit_review(
                        story.pr_number, f"**{actor}:** {comment}", "COMMENT",
                    )

    if event_bus is not None:
        await event_bus.publish(
            StoryCommented(
                report_id=report_id, ticket_id=ticket_id, user=actor, comment=comment,
            ),
        )

    return JSONResponse({"ok": True, "action": "comment"})


def _build_slides(report) -> list[dict]:
    """Build an ordered list of slide descriptors from a DemoReport.

    Top-level walkthrough videos are surfaced right after the title slide so
    viewers land on the demo video without having to click through stories.
    """
    slides: list[dict] = []

    # Slide 0: Title
    slides.append({
        "type": "title",
        "project": report.project_id,
        "date": report.created_at.strftime("%Y-%m-%d %H:%M UTC"),
        "summary": report.summary,
        "gates_pass": report.all_gates_pass,
    })

    # Top-level walkthrough videos come right after the title
    videos = [a for a in report.artifacts if a.type.value == "video"]
    for v in videos:
        slides.append({
            "type": "artifact_video",
            "artifact": v,
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

        # Per-story video slide
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

    # Agent learnings
    if report.agent_learnings:
        slides.append({
            "type": "learnings",
            "learnings": report.agent_learnings,
        })

    return slides
