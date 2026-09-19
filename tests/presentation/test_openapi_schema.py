"""The OpenAPI schema builds — and route annotations stay resolvable.

`GET /swarm/openapi.json` answered 500 in production for as long as anyone
had looked (#144): two Mattermost callback handlers were annotated
`starlette.requests.Request` in modules that defer annotations
(`from __future__ import annotations`), with `import starlette.requests`
inside the function body. The annotation is then the *string*
"starlette.requests.Request", FastAPI resolves annotations against module
globals where `starlette` does not exist, and pydantic raises
`PydanticUserError: TypeAdapter[...] is not fully defined` for the whole
schema — every route lost, not just those two.
"""

from __future__ import annotations

import ast
import pathlib

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "theswarm"

_ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _is_route(decorator: ast.expr) -> bool:
    call = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(call, ast.Attribute) and call.attr in _ROUTE_DECORATORS


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:  # module level only — a function-body import is invisible
        if isinstance(node, ast.Import):
            names.update((alias.asname or alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update((alias.asname or alias.name) for alias in node.names)
    return names


def _dotted_root(annotation: ast.expr) -> str | None:
    node = annotation
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) and isinstance(annotation, ast.Attribute) else None


def test_no_route_handler_is_annotated_with_an_unimportable_dotted_type():
    offenders: list[str] = []

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        available = _module_level_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(_is_route(d) for d in node.decorator_list):
                continue
            for arg in (*node.args.args, *node.args.kwonlyargs):
                root = _dotted_root(arg.annotation) if arg.annotation else None
                if root and root not in available:
                    offenders.append(
                        f"{path.relative_to(SRC.parent.parent)}:{node.lineno} "
                        f"{node.name}({arg.arg}: {ast.unparse(arg.annotation)}) — "
                        f"'{root}' is not imported at module level"
                    )

    assert not offenders, (
        "These route handlers are annotated with a dotted type whose root is "
        "imported inside a function. With deferred annotations FastAPI cannot "
        "resolve it and the whole OpenAPI schema fails (#144):\n  "
        + "\n  ".join(offenders)
    )


async def test_the_schema_builds(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )

    schema = app.openapi()

    assert schema["openapi"].startswith("3.")
    assert schema["paths"]
    await conn.close()
