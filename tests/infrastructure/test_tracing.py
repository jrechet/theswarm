"""V2 runtime, M2: the tracing module — spans nest, ids exist, exceptions mark."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from theswarm.infrastructure import tracing


@pytest.fixture
def exporter():
    memory = InMemorySpanExporter()
    tracing.setup_tracing(seq_url="", exporter=memory, batch=False)
    yield memory
    tracing.shutdown_tracing()


def test_spans_nest_and_carry_attributes(exporter):
    with tracing.span("cycle", **{"swarm.cycle_id": "abc"}):
        with tracing.span("phase.po_morning", **{"swarm.role": "PO"}):
            with tracing.span("claude.call", **{"swarm.model": "claude-haiku-4-5", "swarm.cost_usd": 0.01}):
                pass
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"cycle", "phase.po_morning", "claude.call"}
    assert spans["claude.call"].parent.span_id == spans["phase.po_morning"].context.span_id
    assert spans["phase.po_morning"].parent.span_id == spans["cycle"].context.span_id
    assert spans["cycle"].attributes["swarm.cycle_id"] == "abc"
    assert spans["claude.call"].attributes["swarm.cost_usd"] == 0.01
    assert len({s.context.trace_id for s in spans.values()}) == 1


def test_trace_id_is_readable_inside_a_span_and_empty_outside(exporter):
    assert tracing.current_trace_id() == ""
    with tracing.span("cycle") as current:
        trace_id = tracing.current_trace_id()
        assert len(trace_id) == 32
        assert trace_id == format(current.get_span_context().trace_id, "032x")
        assert len(tracing.current_span_id()) == 16
    assert tracing.current_trace_id() == ""


def test_an_exception_marks_the_span_and_propagates(exporter):
    with pytest.raises(RuntimeError, match="boom"):
        with tracing.span("claude.call"):
            raise RuntimeError("boom")
    (finished,) = exporter.get_finished_spans()
    assert finished.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in finished.events)


def test_attributes_are_cleaned_for_otel(exporter):
    with tracing.span("x", none=None, number=3, flag=True, obj={"a": 1}) as current:
        tracing.set_attributes(current, later="v", skipped=None)
    (finished,) = exporter.get_finished_spans()
    assert "none" not in finished.attributes
    assert finished.attributes["number"] == 3
    assert finished.attributes["flag"] is True
    assert finished.attributes["obj"] == "{'a': 1}"
    assert finished.attributes["later"] == "v"
    assert "skipped" not in finished.attributes


def test_without_a_provider_spans_are_noops_but_do_not_fail():
    tracing.shutdown_tracing()
    with tracing.span("cycle") as current:
        assert tracing.current_trace_id() == ""
        tracing.set_attributes(current, a=1)


def test_the_seq_exporter_targets_the_otlp_traces_endpoint():
    exporter = tracing.seq_exporter("https://logs.example.com/", api_key="k")
    assert exporter._endpoint == "https://logs.example.com/ingest/otlp/v1/traces"
    assert exporter._headers.get("X-Seq-ApiKey") == "k"
