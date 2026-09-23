"""GitHub webhook endpoint."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Request, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# V2 M8 — one trigger per repository per minute: a label put on, taken
# off and put back in a hurry is one cycle, not three (the repo lock
# would queue them, each a full cycle).
TRIGGER_COOLDOWN_SECONDS = 60
_last_trigger: dict[str, float] = {}


def _cooling_down(repo: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    last = _last_trigger.get(repo)
    if last is not None and now - last < TRIGGER_COOLDOWN_SECONDS:
        return True
    _last_trigger[repo] = now
    return False


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

    # V2 M8 — the GitHub-native doors, for the owner only
    if handler.is_go_label(event):
        await _handle_go_label(request, event)
        return Response(content="ok", status_code=200)
    instruction = handler.swarm_instruction(event)
    if instruction is not None:
        await _handle_instruction(request, event, instruction)
        return Response(content="ok", status_code=200)

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


def _owner_only(request, event) -> bool:
    from theswarm.presentation.web.routes.auth_routes import owner_login

    handler = request.app.state.webhook_handler
    if handler.is_owner(event, owner_login()):
        return True
    log.info("Webhook: ignoring %s from %s on %s — not the owner",
             event.event_type, event.sender or "?", event.repo_full_name)
    return False


def _repo_allowed(request, repo: str) -> bool:
    allowed = getattr(request.app.state, "allowed_repos", []) or []
    if not allowed or repo in allowed:
        return True
    log.info("Webhook: ignoring event on %s — not an allowed repository", repo)
    return False


async def _handle_go_label(request, event) -> None:
    """`swarm:go` on an issue: build it, then take the label off so the
    same label can ask again later."""
    from theswarm.presentation.web.routes.v2 import start_targeted_cycle

    if not _owner_only(request, event) or not _repo_allowed(request, event.repo_full_name):
        return
    if _cooling_down(event.repo_full_name):
        log.info("Webhook: label on %s#%s ignored — a trigger fired under a minute ago",
                 event.repo_full_name, event.issue_number)
        return
    owner, _, name = event.repo_full_name.partition("/")
    record = await start_targeted_cycle(
        request.app.state, owner, name, event.issue_number,
        f"Label {event.label} on issue #{event.issue_number}",
    )
    log.info("Webhook: %s on %s#%s → cycle %s", event.label, event.repo_full_name,
             event.issue_number, record.id)
    try:
        from theswarm.tools.github import GitHubClient

        await GitHubClient(event.repo_full_name).remove_label(event.issue_number, event.label)
    except Exception:  # noqa: BLE001 — the cycle is started; the label is tidiness
        log.exception("Webhook: could not remove %s from %s#%s", event.label,
                      event.repo_full_name, event.issue_number)


async def _handle_instruction(request, event, instruction: str) -> None:
    """`@swarm <instruction>` on a pull request: the instruction reaches the
    Dev the way a review's REQUEST_CHANGES does — a note on the task issue
    behind CHANGES_MARKER, the task back to `status:ready`, a cycle pinned
    to it; the Dev resumes the PR's branch and the review runs again."""
    from theswarm.agents.techlead import _changes_comment, _task_of_pr
    from theswarm.presentation.web.routes.v2 import start_targeted_cycle
    from theswarm.tools.github import GitHubClient

    if not _owner_only(request, event) or not _repo_allowed(request, event.repo_full_name):
        return
    if not instruction:
        log.info("Webhook: empty @swarm instruction on %s#%s", event.repo_full_name, event.issue_number)
        return
    github = GitHubClient(event.repo_full_name)
    pr = await github.get_pr(event.issue_number)
    if pr is None:
        log.info("Webhook: @swarm on %s#%s — no such pull request", event.repo_full_name, event.issue_number)
        return
    task = _task_of_pr(pr)
    if task is None:
        await github.create_pr_comment(
            pr["number"],
            "I can't tell which task this pull request implements (no `[#N]` in the "
            "title, no `Closes #N` in the body), so I can't send the instruction to the Dev.",
        )
        return
    if _cooling_down(event.repo_full_name):
        log.info("Webhook: @swarm on %s#%s ignored — a trigger fired under a minute ago",
                 event.repo_full_name, event.issue_number)
        return
    await github.add_comment(task, _changes_comment(pr, f"From {event.sender} on the PR: {instruction}", []))
    await github.add_labels(task, ["status:ready"])
    try:
        await github.remove_label(task, "status:review")
    except Exception:  # noqa: BLE001 — the label may not be there
        pass
    owner, _, name = event.repo_full_name.partition("/")
    record = await start_targeted_cycle(
        request.app.state, owner, name, task, f"@swarm on PR #{pr['number']}",
    )
    await github.create_pr_comment(
        pr["number"],
        f"On it — task #{task} is back with the Dev with your instruction "
        f"(cycle `{record.id}`).",
    )


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
