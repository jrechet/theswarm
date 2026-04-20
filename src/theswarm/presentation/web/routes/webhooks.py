"""GitHub webhook endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


_REFUSAL_COMMENT = (
    "Sorry @{user} — you're not on this project's allowlist for "
    "`/swarm implement`. Ping a maintainer if you think this is a mistake."
)


@router.post("/github")
async def github_webhook(request: Request) -> Response:
    """Handle incoming GitHub webhook events."""
    handler = getattr(request.app.state, "webhook_handler", None)
    if handler is None:
        return Response(content="Webhooks not configured", status_code=501)

    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "")

    if not handler.verify_signature(body, signature):
        log.warning("Invalid webhook signature")
        return Response(content="Invalid signature", status_code=401)

    payload = await request.json()
    event = handler.parse_event(event_type, payload)

    # Sprint F P1 — /swarm implement on an issue comment
    if handler.is_implement_command(event):
        await _handle_implement_command(request, event)
        return Response(content="ok", status_code=200)

    allowed_repos = getattr(request.app.state, "allowed_repos", [])
    if handler.should_trigger_cycle(event, allowed_repos):
        log.info(
            "Webhook triggering cycle: repo=%s event=%s",
            event.repo_full_name,
            event.event_type,
        )
        cycle_handler = getattr(request.app.state, "run_cycle_handler", None)
        if cycle_handler is not None:
            from theswarm.application.commands.run_cycle import RunCycleCommand

            # Find project by repo name
            project_repo = request.app.state.project_repo
            projects = await project_repo.list_all()
            for p in projects:
                if str(p.repo) == event.repo_full_name:
                    try:
                        await cycle_handler.handle(
                            RunCycleCommand(
                                project_id=p.id,
                                triggered_by=f"webhook:{event.event_type}",
                            ),
                        )
                    except ValueError as e:
                        log.error("Webhook cycle trigger failed: %s", e)
                    break

    return Response(content="ok", status_code=200)


async def _handle_implement_command(request, event) -> None:
    """React to `/swarm implement` on an issue: auth-check, trigger cycle, or refuse."""
    handler = request.app.state.webhook_handler
    allowed_commenters = getattr(request.app.state, "allowed_commenters", [])

    project_repo = request.app.state.project_repo
    projects = await project_repo.list_all()
    project = next(
        (p for p in projects if str(p.repo) == event.repo_full_name),
        None,
    )
    if project is None:
        log.info("Webhook /swarm implement: no project registered for %s", event.repo_full_name)
        return

    if not handler.is_authorised(event, allowed_commenters):
        log.info(
            "Webhook /swarm implement: refusing unauthorised user %s on %s",
            event.sender,
            event.repo_full_name,
        )
        await _post_refusal(request, event, project)
        return

    cycle_handler = getattr(request.app.state, "run_cycle_handler", None)
    if cycle_handler is None:
        log.warning("Webhook /swarm implement: run_cycle_handler not configured")
        return

    from theswarm.application.commands.run_cycle import RunCycleCommand

    try:
        await cycle_handler.handle(
            RunCycleCommand(
                project_id=project.id,
                triggered_by=f"/swarm implement #{event.issue_number} by {event.sender}",
            ),
        )
        log.info(
            "Webhook /swarm implement: cycle started for %s (issue #%s by %s)",
            event.repo_full_name, event.issue_number, event.sender,
        )
    except ValueError as e:
        log.error("Webhook /swarm implement failed: %s", e)


async def _post_refusal(request, event, project) -> None:
    """Post the polite refusal comment on the issue via VCS factory."""
    vcs_factory = getattr(request.app.state, "vcs_factory", None)
    if vcs_factory is None or event.issue_number is None:
        return
    try:
        vcs = vcs_factory(str(project.repo))
        comment = _REFUSAL_COMMENT.format(user=event.sender)
        poster = getattr(vcs, "post_issue_comment", None)
        if poster is None:
            log.debug("vcs_factory output has no post_issue_comment; skipping refusal")
            return
        await poster(event.issue_number, comment)
    except Exception:
        log.exception("Failed to post refusal comment on %s#%s",
                      event.repo_full_name, event.issue_number)
