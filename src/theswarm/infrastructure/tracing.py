"""OpenTelemetry tracing for a cycle, exported to Seq (V2 runtime, M2).

One trace per cycle, a span per phase, a span per graph node, a span per
Claude call — the tree a person reads in Seq when a cycle went wrong, in
the tool that already holds the logs. Seq ingests OTLP/HTTP natively
(``/ingest/otlp/v1/traces``; version 2025.2 on jrec.fr, probed 2026-09-23),
so no new service is involved (plan decision 3).

The provider is kept on this module rather than through the global
``opentelemetry.trace`` registry: the global can be set once per process,
which makes tests that need their own exporter impossible. Context
propagation (parent → child) still goes through OpenTelemetry's context
variables, so spans nest across ``await`` boundaries as expected.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

log = logging.getLogger(__name__)

TRACER_NAME = "theswarm"
SERVICE_NAME = "theswarm"
OTLP_TRACES_PATH = "/ingest/otlp/v1/traces"

_provider: TracerProvider | None = None


def seq_exporter(seq_url: str, api_key: str = "") -> SpanExporter:
    """The OTLP/HTTP exporter pointed at Seq's traces endpoint."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    headers = {"X-Seq-ApiKey": api_key} if api_key else {}
    return OTLPSpanExporter(endpoint=seq_url.rstrip("/") + OTLP_TRACES_PATH, headers=headers)


def setup_tracing(
    *,
    seq_url: str | None = None,
    api_key: str | None = None,
    exporter: SpanExporter | None = None,
    batch: bool = True,
) -> TracerProvider:
    """Install the provider. Without a Seq URL or an exporter, spans are
    created (so ids exist for logs) but exported nowhere."""
    global _provider
    if seq_url is None:
        seq_url = os.getenv("SEQ_URL", "")
    if api_key is None:
        api_key = os.getenv("SEQ_API_KEY", "")
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    if exporter is None and seq_url:
        exporter = seq_exporter(seq_url, api_key)
    if exporter is not None:
        processor = BatchSpanProcessor(exporter) if batch else SimpleSpanProcessor(exporter)
        provider.add_span_processor(processor)
        log.info("Tracing: exporting spans to %s", seq_url or type(exporter).__name__)
    _provider = provider
    return provider


def shutdown_tracing() -> None:
    """Flush and drop the provider — for a clean process exit, and tests."""
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:  # noqa: BLE001 — shutdown is best effort
            log.debug("Tracer provider shutdown failed", exc_info=True)
    _provider = None


def tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer(TRACER_NAME)
    return trace.get_tracer(TRACER_NAME)  # the API's no-op tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Span]:
    """A span that is the current one for its block; exceptions are recorded
    and re-raised, the span marked as an error."""
    with tracer().start_as_current_span(name, attributes=_clean(attributes)) as current:
        try:
            yield current
        except BaseException as exc:
            current.record_exception(exc)
            current.set_status(Status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}"[:200]))
            raise


def set_attributes(current: Span, **attributes: Any) -> None:
    current.set_attributes(_clean(attributes))


def current_trace_id() -> str:
    """The active trace's id as 32 hex chars — "" outside any span."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else ""


def current_span_id() -> str:
    context = trace.get_current_span().get_span_context()
    return format(context.span_id, "016x") if context.is_valid else ""


def _clean(attributes: dict[str, Any]) -> dict[str, Any]:
    """OpenTelemetry accepts str/bool/int/float (and sequences of them);
    drop None, stringify the rest."""
    cleaned: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned
