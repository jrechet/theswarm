"""Every decision read out of prose is counted (V2 runtime M3 → M7).

M7 wanted the text parsers gone "once their counter stayed at zero", and
there was no counter. `note_text_fallback` is it: a log line Seq can count
and an attribute on the call's span.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest

from theswarm.agents import base, dev, techlead
from theswarm.agents.base import note_text_fallback


def test_a_fallback_is_logged_with_its_kind_and_backend(caplog):
    caplog.set_level(logging.INFO, logger="theswarm.agents.base")

    note_text_fallback("review", SimpleNamespace(backend="api"), produced=True)

    assert "Text fallback used: review (backend=api, produced=True)" in caplog.text


def test_a_result_without_a_backend_still_counts(caplog):
    caplog.set_level(logging.INFO, logger="theswarm.agents.base")

    note_text_fallback("file_blocks", None, produced=False)

    assert "Text fallback used: file_blocks (backend=?, produced=False)" in caplog.text


def test_the_current_span_carries_the_kind():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("t").start_as_current_span("claude.call"):
        note_text_fallback("breakdown", SimpleNamespace(backend="api"))

    (span,) = exporter.get_finished_spans()
    assert span.attributes["swarm.text_fallback"] == "breakdown"


@pytest.mark.parametrize("module,function,kinds", [
    (dev, "implement_task", {"file_blocks", "already_satisfied"}),
    (dev, "retry_implement", {"file_blocks"}),
])
def test_every_dev_fallback_branch_counts(module, function, kinds):
    source = inspect.getsource(getattr(module, function))
    for kind in kinds:
        assert f'note_text_fallback("{kind}"' in source, (function, kind)


def test_every_techlead_fallback_branch_counts():
    source = inspect.getsource(techlead)
    assert source.count('note_text_fallback("breakdown"') == 1
    assert source.count('note_text_fallback("review"') == 1


def test_a_structured_answer_is_not_a_fallback(caplog, monkeypatch):
    """The SDK path must stay silent, or the counter never reaches zero."""
    from theswarm.agents.schemas import ReviewVerdict

    caplog.set_level(logging.INFO, logger="theswarm.agents.base")
    structured = ReviewVerdict(decision="APPROVE", summary="fine", issues=[]).model_dump()
    result = SimpleNamespace(text="", structured=structured, backend="sdk")

    assert techlead._verdict_from_structure(result) is not None
    assert "Text fallback used" not in caplog.text


def test_the_counter_lives_where_the_agents_can_import_it():
    assert base.note_text_fallback is note_text_fallback
