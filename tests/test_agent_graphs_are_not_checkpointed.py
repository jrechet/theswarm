"""Agent graphs run inside the durable cycle graph without inheriting its
checkpointer (V2 M4 follow-up, prod cycle ddd989b4e51e).

LangGraph hands a parent's checkpointer to any compiled graph invoked from
one of its nodes; the agent graphs' state carries live clients, and the
first prod cycle on the durable graph died in po_morning with
"Type is not msgpack serializable: GitHubClient".
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from theswarm.agents.dev import build_dev_graph
from theswarm.agents.po import build_po_graph
from theswarm.agents.qa import build_qa_graph
from theswarm.agents.techlead import build_techlead_graph


@pytest.mark.parametrize("build", [build_po_graph, build_techlead_graph, build_dev_graph, build_qa_graph])
def test_agent_graphs_compile_without_a_checkpointer(build):
    assert build().checkpointer is False


class _Parent(TypedDict, total=False):
    result: str


async def test_an_agent_graph_inside_a_checkpointed_node_does_not_serialise_live_clients(tmp_path):
    """The exact prod shape: a sync-durability parent on SQLite, an agent
    graph with a live object in its state, invoked from a node."""
    from theswarm.cycle_graph import _invoke_agent

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "ck.db")) as saver:
        async def node(state: _Parent) -> dict:
            out = await _invoke_agent(build_dev_graph(), {
                "phase": "development", "github": None, "claude": MagicMock(), "workspace": None,
            })
            return {"result": str(out.get("task"))}

        graph = StateGraph(_Parent)
        graph.add_node("node", node)
        graph.set_entry_point("node")
        graph.add_edge("node", END)
        compiled = graph.compile(checkpointer=saver)
        final = await compiled.ainvoke({}, {"configurable": {"thread_id": "t"}}, durability="sync")
        assert final["result"] == "None"


async def test_a_detached_agent_graph_still_nests_its_spans_under_the_phase():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from theswarm.cycle_graph import _invoke_agent
    from theswarm.infrastructure import tracing

    exporter = InMemorySpanExporter()
    tracing.setup_tracing(seq_url="", exporter=exporter, batch=False)
    try:
        with tracing.span("phase.po_morning"):
            await _invoke_agent(build_po_graph(), {"phase": "morning"})
    finally:
        tracing.shutdown_tracing()
    spans = exporter.get_finished_spans()
    phase = next(s for s in spans if s.name == "phase.po_morning")
    node = next(s for s in spans if s.name == "node.load_context")
    assert node.parent.span_id == phase.context.span_id


async def test_the_phase_budget_cancels_a_detached_agent_graph():
    import asyncio

    from theswarm.cycle_graph import _invoke_agent

    class _Slow:
        async def ainvoke(self, state):
            await asyncio.sleep(30)
            return {}

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(_invoke_agent(_Slow(), {}), timeout=0.05)
