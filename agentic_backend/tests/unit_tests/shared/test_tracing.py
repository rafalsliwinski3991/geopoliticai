import asyncio
import sys
import types
from typing import Any

import pytest
from openinference.semconv.trace import SpanAttributes
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from shared import tracing


def _install_fake_phoenix_otel(
    monkeypatch: pytest.MonkeyPatch, register: object
) -> None:
    """Stub sys.modules so tests don't require the real package installed."""
    otel_module = types.ModuleType("phoenix.otel")
    otel_module.register = register  # type: ignore[attr-defined]
    phoenix_module = types.ModuleType("phoenix")
    phoenix_module.otel = otel_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix", phoenix_module)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel_module)


def test_init_tracing_noop_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no collector configured, tracing stays off and nothing is registered."""
    # Arrange
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_registers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phoenix gets batched HTTP export: one blocking request per span would
    stall the event loop of a CI eval talking to the VPS."""
    # Arrange
    monkeypatch.setenv(
        "PHOENIX_COLLECTOR_ENDPOINT", "https://politicalagent.eu/phoenix/v1/traces"
    )
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "test-project")
    calls: list[dict[str, object]] = []
    _install_fake_phoenix_otel(monkeypatch, lambda **kwargs: calls.append(kwargs))
    # Act
    first = tracing.init_tracing()
    second = tracing.init_tracing()
    # Assert
    assert first is True
    assert second is True
    assert calls == [
        {
            "endpoint": "https://politicalagent.eu/phoenix/v1/traces",
            "project_name": "test-project",
            "batch": True,
            "protocol": "http/protobuf",
            "auto_instrument": True,
        }
    ]


def test_init_tracing_defaults_the_project_to_geopoliticai_expert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The app's own traces keep one project unless an operator renames it."""
    # Arrange
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006/v1/traces")
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    calls: list[dict[str, object]] = []
    _install_fake_phoenix_otel(monkeypatch, lambda **kwargs: calls.append(kwargs))
    # Act
    tracing.init_tracing()
    # Assert
    assert calls[0]["project_name"] == "geopoliticai-expert"


def test_init_tracing_swallows_register_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collector outage must never fail a request."""
    # Arrange
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://unroutable.invalid:6006")

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("collector unreachable")

    _install_fake_phoenix_otel(monkeypatch, _boom)
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_start_span_records_a_named_span(
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    # Act
    with tracing.start_span("fetch_source") as span:
        span.end()
    # Assert
    spans = list(captured_spans.get_finished_spans())
    assert [span.name for span in spans] == ["fetch_source"]


def test_start_span_marks_the_span_a_chain(
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    # Act
    with tracing.start_span("fetch_source"):
        pass
    # Assert
    (span,) = captured_spans.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes[SpanAttributes.OPENINFERENCE_SPAN_KIND] == "CHAIN"


def test_start_span_parents_on_the_langchain_span_when_tracing_is_on(
    monkeypatch: pytest.MonkeyPatch, captured_spans: InMemorySpanExporter
) -> None:
    # Arrange
    tracer = trace.get_tracer("test")
    span = tracer.start_span("parent")
    monkeypatch.setattr(tracing, "get_langchain_span", lambda: span, raising=False)
    monkeypatch.setattr(tracing, "_initialized", True)
    # Act
    with tracing.start_span("fetch_source") as child:
        child.end()
    span.end()
    # Assert
    finished = {s.name: s for s in captured_spans.get_finished_spans()}
    child_parent = finished["fetch_source"].parent
    assert child_parent is not None
    assert child_parent.span_id == span.get_span_context().span_id


def test_start_span_skips_the_langchain_lookup_when_tracing_is_off(
    monkeypatch: pytest.MonkeyPatch, captured_spans: InMemorySpanExporter
) -> None:
    # Arrange
    calls: list[object] = []

    def spy() -> object:
        calls.append("called")
        raise RuntimeError("must not be called")

    monkeypatch.setattr(tracing, "get_langchain_span", spy, raising=False)
    monkeypatch.setattr(tracing, "_initialized", False)
    # Act
    with tracing.start_span("fetch_source") as span:
        span.end()
    # Assert
    assert calls == []
    assert [span.name for span in captured_spans.get_finished_spans()] == [
        "fetch_source"
    ]


def test_start_span_survives_a_failing_langchain_lookup(
    monkeypatch: pytest.MonkeyPatch, captured_spans: InMemorySpanExporter
) -> None:
    # Arrange
    def broken() -> object:
        raise AttributeError("no instrumented run here")

    monkeypatch.setattr(tracing, "get_langchain_span", broken, raising=False)
    monkeypatch.setattr(tracing, "_initialized", True)
    # Act
    with tracing.start_span("fetch_source") as span:
        span.end()
    # Assert
    finished = list(captured_spans.get_finished_spans())
    assert [s.name for s in finished] == ["fetch_source"]
    assert finished[0].parent is None


@pytest.mark.anyio
async def test_bind_trace_user_puts_the_user_in_context() -> None:
    # Arrange
    outcomes: dict[str, Any] = {}

    async def sibling() -> None:
        await asyncio.sleep(0)
        outcomes["sibling"] = otel_context.get_value(SpanAttributes.USER_ID)

    # Act
    task = asyncio.create_task(sibling())
    await asyncio.sleep(0)  # let the sibling task start before the bind
    tracing.bind_trace_user(7)
    bound = otel_context.get_value(SpanAttributes.USER_ID)
    await task

    # Assert
    assert bound == "7"
    assert outcomes["sibling"] is None


@pytest.mark.anyio
async def test_start_span_carries_the_bound_user(
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    tracing.bind_trace_user(7)
    # Act
    with tracing.start_span("fetch_source") as span:
        span.end()
    # Assert
    finished = list(captured_spans.get_finished_spans())
    attributes = finished[0].attributes
    assert attributes is not None
    assert attributes[SpanAttributes.USER_ID] == "7"
