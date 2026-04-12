"""GitHub webhook endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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
