"""`/mcp` — the swarm's MCP server over Streamable HTTP (phase B, B5).

Behind the wall like every page: the access key as `Authorization: Bearer`,
owner only (a member's session is refused by the wall's allow-list, and
again here). A client is added with:

    claude mcp add --transport http theswarm https://<host>/swarm/mcp \\
        --header "Authorization: Bearer <access key>"
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from theswarm.presentation.web.mcp import protocol
from theswarm.presentation.web.mcp.tools import TOOLS

log = logging.getLogger(__name__)

router = APIRouter()
MAX_BODY_BYTES = 200_000


async def _owner(request: Request) -> bool:
    from theswarm.presentation.web.routes.customers import current_actor

    actor = await current_actor(request)
    return actor is not None and actor.is_owner


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if not await _owner(request):
        return JSONResponse({"detail": "The MCP server is the owner's"}, status_code=403)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return JSONResponse(protocol._error(None, protocol.INVALID_REQUEST, "The message is too large"), status_code=413)
    try:
        message = json.loads(raw or b"null")
    except ValueError:
        return JSONResponse(protocol._error(None, protocol.PARSE_ERROR, "Not JSON"), status_code=400)
    if isinstance(message, list):  # batches left the protocol in 2025-06-18
        return JSONResponse(protocol._error(None, protocol.INVALID_REQUEST, "One message at a time"), status_code=400)
    from theswarm.agents.devops import build_sha

    answer = await protocol.handle(message, TOOLS, request.app.state, version=(build_sha() or "")[:7])
    if answer is None:
        return Response(status_code=202)
    return JSONResponse(answer)


@router.get("/mcp")
async def mcp_get() -> Response:
    """No server-sent stream: this server only answers."""
    return Response(status_code=405, headers={"Allow": "POST"})
