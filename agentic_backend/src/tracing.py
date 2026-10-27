"""OpenTelemetry boundary: optional Phoenix span export.

Tracing is a deliberate exception to this repo's hard-fail rule: an
unreachable collector, a missing dependency, or an exporter error must never
fail a request, so every failure here is swallowed and logged instead of
raised.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from openinference.instrumentation import OITracer, TraceConfig
from openinference.instrumentation.langchain import (
    get_current_span as get_langchain_span,
)
from openinference.semconv.trace import SpanAttributes
from opentelemetry import context as otel_context
from opentelemetry import trace

from config import get_trace_endpoint

logger = logging.getLogger(__name__)
# The name every span this repo opens is created under (not the project name).
TRACER_NAME = "geopoliticai"
# The app's own traces; an eval experiment moves its spans into its own project.
DEFAULT_PROJECT_NAME = "geopoliticai-expert"

_initialized = False


def init_tracing() -> bool:
    """Register Phoenix tracing when configured; never raise.

    Returns True when tracing is active after this call: it was already
    active, or this call activated it. A Phoenix behind nginx Basic Auth gets
    its header from `PHOENIX_CLIENT_HEADERS`, which `phoenix.otel` reads itself.
    Spans export in batches from a background thread: the CI evals send them
    over the internet to the VPS, where one blocking request per span would
    stall the event loop and eat into the agents' wall caps.
    """
    global _initialized
    if _initialized:
        return True
    endpoint = get_trace_endpoint()
    if not endpoint or not endpoint.strip():
        logger.debug("PHOENIX_COLLECTOR_ENDPOINT unset; tracing disabled.")
        return False
    try:
        from phoenix.otel import register

        register(
            endpoint=endpoint,
            project_name=os.getenv("PHOENIX_PROJECT_NAME", DEFAULT_PROJECT_NAME),
            batch=True,
            # Stated, not inferred: phoenix.otel infers HTTP only from a path of
            # exactly `/v1/traces`, and the VPS endpoint is `/phoenix/v1/traces`.
            protocol="http/protobuf",
            auto_instrument=True,
        )
    except Exception as exc:
        logger.warning("Tracing disabled: %s", exc)
        return False
    _initialized = True
    return True


@contextmanager
def start_span(name: str) -> Iterator[trace.Span]:
    """Open a span inside the current LangChain run's span, or the current span.

    The OpenInference LangChain tracer never makes its spans current (attaching
    from callbacks is unsafe, `openinference/instrumentation/langchain/_tracer.py`),
    so a plain `start_as_current_span` in a node or tool would start a new
    trace. The run's span is looked up only once tracing is on: with no tracer,
    the lookup prints a warning to stdout on every call. `OITracer` copies the
    context attributes (`user.id` from `bind_trace_user`) onto the span, which a
    plain tracer does not. Each span is a `CHAIN`, so Phoenix shows a kind
    instead of `UNKNOWN`. Without a configured provider the span records
    nothing, so tracing still cannot fail a request.
    """
    parent = None
    if _initialized:
        try:
            parent = get_langchain_span()
        except Exception as exc:  # noqa: BLE001 - tracing never fails a request
            logger.debug("No LangChain parent span: %s", exc)
    parent_context = trace.set_span_in_context(parent) if parent is not None else None
    tracer = OITracer(trace.get_tracer(TRACER_NAME), config=TraceConfig())
    with tracer.start_as_current_span(
        name, context=parent_context, openinference_span_kind="chain"
    ) as span:
        yield span


def bind_trace_user(user_id: int) -> None:
    """Put `user.id` on every span this request opens from here on.

    The tracing twin of `config.bind_log_context`, called in the request
    handler. It is never detached: the request task's context ends with the
    request, and detaching from inside the streaming generator logs a
    cross-context error when a client disconnects (probe, plan 2026Oct13).
    The id is the raw Django id (brainstorm 2026Oct13 Q3).
    """
    otel_context.attach(otel_context.set_value(SpanAttributes.USER_ID, str(user_id)))
