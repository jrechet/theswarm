"""MCP over Streamable HTTP, the part a tool server needs — and no more.

One endpoint takes a JSON-RPC 2.0 message by POST and answers it as
`application/json`: `initialize`, `ping`, `tools/list`, `tools/call`; a
notification is accepted with 202 and no body. No session, no server-sent
stream, no resources or prompts: every call stands alone, which is what the
transport allows a server that only answers.

Written here rather than on the `mcp` package, which the Agent SDK brings in
transitively: nothing of the swarm should break when that package moves, and
`docs/DEPENDENCIES.md` gains no row.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_NAME = "theswarm"

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class ToolError(Exception):
    """A tool that cannot do what was asked, said in words for the caller:
    the answer is a tool result with `isError`, not a protocol error."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[Any, dict], Awaitable[Any]]
    properties: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()
    writes: bool = False  # changes something: said to the client as a hint

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": list(self.required),
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": not self.writes, "destructiveHint": False, "openWorldHint": False},
        }


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _check_arguments(tool: Tool, arguments: dict) -> str:
    missing = [name for name in tool.required if arguments.get(name) in (None, "")]
    if missing:
        return f"{tool.name} needs {', '.join(missing)}"
    unknown = sorted(set(arguments) - set(tool.properties))
    if unknown:
        return f"{tool.name} takes {', '.join(tool.properties) or 'no argument'}, not {', '.join(unknown)}"
    for name, value in arguments.items():
        wanted = tool.properties[name].get("type")
        ok = {"string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
              "boolean": isinstance(value, bool)}.get(wanted, True)
        if not ok:
            return f"{tool.name}: {name} is a {wanted}"
    return ""


async def handle(message: Any, tools: dict[str, Tool], state: Any, *, version: str = "") -> dict | None:
    """The answer to one JSON-RPC message; None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST,
                      "A JSON-RPC 2.0 request with a method")
    method, request_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:
        return None  # a notification (notifications/initialized, cancelled…): nothing to answer
    if not isinstance(params, dict):
        return _error(request_id, INVALID_PARAMS, "params is an object")
    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        return _result(request_id, {
            "protocolVersion": asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "TheSwarm", "version": version or "0"},
            "instructions": (
                "TheSwarm builds features on registered GitHub repositories with a team of agents. Read with "
                "list_projects, list_cycles, get_cycle and get_team; start a feature with start_feature; talk to a "
                "running cycle with say_to_cycle, pause it with pause_cycle. A cycle takes tens of minutes: start "
                "it, then read get_cycle now and then."
            ),
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [tool.schema() for tool in tools.values()]})
    if method == "tools/call":
        tool = tools.get(str(params.get("name") or ""))
        if tool is None:
            return _error(request_id, INVALID_PARAMS, f"No tool called {params.get('name')!r}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "arguments is an object")
        wrong = _check_arguments(tool, arguments)
        try:
            if wrong:
                raise ToolError(wrong)
            value = await tool.handler(state, arguments)
        except ToolError as exc:
            return _result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
        except Exception as exc:  # noqa: BLE001 — a tool that broke is the tool's error, said plainly
            log.exception("MCP tool %s failed", tool.name)
            return _result(request_id, {"content": [{"type": "text", "text": f"{tool.name} failed: {type(exc).__name__}"}],
                                        "isError": True})
        text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)
        result: dict = {"content": [{"type": "text", "text": text}], "isError": False}
        if isinstance(value, dict):
            result["structuredContent"] = json.loads(json.dumps(value, default=str))
        return _result(request_id, result)
    return _error(request_id, METHOD_NOT_FOUND, f"{method} is not a method of this server")
