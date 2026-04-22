"""Dashboard chat routes.

- ``GET  /chat`` — global chat page (portfolio-wide thread list)
- ``GET  /chat/{thread_id}`` — single thread view (full page)
- ``POST /chat/{thread_id}/messages`` — append a message (HTMX form)
- ``GET  /chat/{thread_id}/stream`` — SSE stream of new messages
- ``GET  /projects/{project_id}/chat`` — HTMX fragment: chat card on project page
- ``POST /projects/{project_id}/chat/messages`` — shorthand: post to the
  project team thread (codename empty)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from theswarm.domain.chat.threads import ChatThread

router = APIRouter()


def _service(request: Request):
    svc = getattr(request.app.state, "chat_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="chat service not configured")
    return svc


def _repo(request: Request):
    repo = getattr(request.app.state, "chat_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="chat repo not configured")
    return repo


def _templates(request: Request):
    return request.app.state.templates


# ── Portfolio chat page ──────────────────────────────────────────────


@router.get("/chat", response_class=HTMLResponse)
async def chat_index(request: Request) -> HTMLResponse:
    repo = getattr(request.app.state, "chat_repo", None)
    threads = await repo.list_threads() if repo is not None else []
    return _templates(request).TemplateResponse(
        "chat_index.html",
        {"request": request, "threads": threads},
    )


# ── Per-thread page (full view) ──────────────────────────────────────


@router.get("/chat/{thread_id}", response_class=HTMLResponse)
async def chat_thread_page(request: Request, thread_id: str) -> HTMLResponse:
    repo = _repo(request)
    thread = await repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    messages = await repo.list_messages(thread_id, limit=200)
    return _templates(request).TemplateResponse(
        "chat_thread.html",
        {"request": request, "thread": thread, "messages": messages},
    )


# ── Append message (HTMX form) ───────────────────────────────────────


@router.post("/chat/{thread_id}/messages", response_class=HTMLResponse)
async def chat_post_message(
    request: Request, thread_id: str, body: str = Form(...),
) -> HTMLResponse:
    repo = _repo(request)
    svc = _service(request)
    thread = await repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")
    result = await svc.send_user_message(
        project_id=thread.project_id,
        body=body,
        thread_codename=thread.codename,
    )
    # Return just the rendered messages the client should append
    return _templates(request).TemplateResponse(
        "chat_messages_fragment.html",
        {
            "request": request,
            "messages": [result.user_message] + (
                [result.agent_reply] if result.agent_reply else []
            ),
            "thread": result.thread,
        },
    )


# ── SSE stream ───────────────────────────────────────────────────────


@router.get("/chat/{thread_id}/stream")
async def chat_stream(request: Request, thread_id: str):
    repo = _repo(request)
    thread = await repo.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="thread not found")

    async def generator():
        last_seen: datetime | None = None
        # Prime with existing messages
        initial = await repo.list_messages(thread_id, limit=50)
        for m in initial:
            last_seen = m.created_at
            yield _sse("message", _msg_to_dict(m))
        # Poll-based stream (low overhead; avoids wiring a pub/sub topic)
        while True:
            if await request.is_disconnected():
                return
            await asyncio.sleep(1.5)
            new = await repo.list_messages(thread_id, after=last_seen, limit=100)
            for m in new:
                last_seen = m.created_at
                yield _sse("message", _msg_to_dict(m))

    return StreamingResponse(generator(), media_type="text/event-stream")


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _msg_to_dict(m) -> dict:
    return {
        "id": m.id,
        "thread_id": m.thread_id,
        "author_kind": m.author_kind.value,
        "author_display": m.author_display,
        "body": m.body,
        "created_at": m.created_at.isoformat(),
        "intent_action": m.intent_action,
    }


# ── Project chat fragment (for project detail page) ──────────────────


@router.get("/projects/{project_id}/chat", response_class=HTMLResponse)
async def project_chat_fragment(
    request: Request, project_id: str,
) -> HTMLResponse:
    repo = getattr(request.app.state, "chat_repo", None)
    if repo is None:
        return HTMLResponse("", status_code=200)
    team_thread = await repo.get_or_create_thread(
        project_id=project_id, codename="", role="",
        title=f"{project_id} · team",
    )
    messages = await repo.list_messages(team_thread.id, limit=20)
    return _templates(request).TemplateResponse(
        "chat_project_fragment.html",
        {
            "request": request,
            "project_id": project_id,
            "thread": team_thread,
            "messages": messages,
        },
    )


@router.post("/projects/{project_id}/chat/messages", response_class=HTMLResponse)
async def project_chat_post(
    request: Request, project_id: str, body: str = Form(...),
) -> HTMLResponse:
    svc = _service(request)
    result = await svc.send_user_message(project_id=project_id, body=body)
    return _templates(request).TemplateResponse(
        "chat_messages_fragment.html",
        {
            "request": request,
            "messages": [result.user_message] + (
                [result.agent_reply] if result.agent_reply else []
            ),
            "thread": result.thread,
        },
    )
