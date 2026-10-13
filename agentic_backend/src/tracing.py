"""OpenTelemetry boundary: optional Phoenix or Arize AX span export.

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

from config import get_arize_platform, get_trace_endpoint

logger = logging.getLogger(__name__)
# The name every span this repo opens is created under (not the project name).
TRACER_NAME = "geopoliticai"

_initialized = False


def init_tracing() -> bool:
    """Register Phoenix or Arize AX tracing when configured; never raise.

    Returns True when tracing is active after this call: it was already
    active, or this call activated it.
    """
    global _initialized
    if _initialized:
        return True
    try:
        endpoint = get_trace_endpoint()
    except ValueError as exc:
        logger.warning("Tracing disabled: %s", exc)
        return False
    if not endpoint or not endpoint.strip():
        platform = get_arize_platform()
        logger.debug(
            "%s collector endpoint unset; tracing disabled.",
            platform,
        )
        return False
    try:
        project_name = os.getenv("ARIZE_PROJECT_NAME", "geopoliticai-expert")
        if get_arize_platform() == "AX":
            from arize.otel import register as register_ax

            api_key = os.getenv("ARIZE_API_KEY")
            space_id = os.getenv("ARIZE_SPACE_ID")
            if not space_id or not api_key:
                raise ValueError(
                    "ARIZE_SPACE_ID and ARIZE_API_KEY are required for AX tracing"
                )
            register_ax(
                endpoint=endpoint,
                space_id=space_id,
                api_key=api_key,
                project_name=project_name,
                auto_instrument=True,
            )
        else:
            from phoenix.otel import register

            # Local Phoenix runs without auth; the AX key must never reach it.
            register(
                endpoint=endpoint,
                project_name=project_name,
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
    plain tracer does not. Without a configured provider the span records
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
    with tracer.start_as_current_span(name, context=parent_context) as span:
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
