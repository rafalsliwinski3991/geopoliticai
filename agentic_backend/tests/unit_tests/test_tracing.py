import sys
import types

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracing


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


def _install_fake_arize_otel(monkeypatch: pytest.MonkeyPatch, register: object) -> None:
    otel_module = types.ModuleType("arize.otel")
    otel_module.register = register  # type: ignore[attr-defined]
    arize_module = types.ModuleType("arize")
    arize_module.otel = otel_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arize", arize_module)
    monkeypatch.setitem(sys.modules, "arize.otel", otel_module)


def test_init_tracing_noop_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("ARIZE_PLATFORM", raising=False)
    monkeypatch.delenv("ARIZE_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_disabled_for_unsupported_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "datadog")
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_swallows_register_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "AX")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "http://unroutable.invalid:6006")
    monkeypatch.setenv("ARIZE_SPACE_ID", "test-space")
    monkeypatch.setenv("ARIZE_API_KEY", "test-arize-key")

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("collector unreachable")

    _install_fake_arize_otel(monkeypatch, _boom)
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_registers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "AX")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "http://phoenix:6006")
    monkeypatch.setenv("ARIZE_SPACE_ID", "test-space")
    monkeypatch.setenv("ARIZE_PROJECT_NAME", "test-project")
    monkeypatch.setenv("ARIZE_API_KEY", "test-arize-key")
    calls: list[dict[str, object]] = []

    def _spy(**kwargs: object) -> None:
        calls.append(kwargs)

    _install_fake_arize_otel(monkeypatch, _spy)

    # Act + Assert
    assert tracing.init_tracing() is True
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "http://phoenix:6006"
    assert calls[0]["space_id"] == "test-space"
    assert calls[0]["project_name"] == "test-project"
    assert calls[0]["api_key"] == "test-arize-key"
    assert calls[0]["auto_instrument"] is True

    # A second call finds tracing already active: not a failure.
    assert tracing.init_tracing() is True
    assert len(calls) == 1


def test_init_tracing_accepts_phoenix_endpoint_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "PHOENIX")
    monkeypatch.delenv("ARIZE_COLLECTOR_ENDPOINT", raising=False)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006")
    monkeypatch.setenv("ARIZE_API_KEY", "ax-secret")
    calls: list[dict[str, object]] = []

    def _spy(**kwargs: object) -> None:
        calls.append(kwargs)

    _install_fake_phoenix_otel(monkeypatch, _spy)

    # Act + Assert
    assert tracing.init_tracing() is True
    assert calls[0]["endpoint"] == "http://phoenix:6006"
    # The AX secret must never reach a Phoenix collector.
    assert "api_key" not in calls[0]


def test_init_tracing_swallows_phoenix_register_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "PHOENIX")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://unroutable.invalid:6006")

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("collector unreachable")

    _install_fake_phoenix_otel(monkeypatch, _boom)
    # Act + Assert
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


@pytest.mark.parametrize("missing", ["ARIZE_SPACE_ID", "ARIZE_API_KEY"])
def test_init_tracing_ax_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    # Arrange
    monkeypatch.setenv("ARIZE_PLATFORM", "AX")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "http://ax:6006")
    monkeypatch.setenv("ARIZE_SPACE_ID", "test-space")
    monkeypatch.setenv("ARIZE_API_KEY", "test-arize-key")
    monkeypatch.delenv(missing)
    calls: list[dict[str, object]] = []
    _install_fake_arize_otel(monkeypatch, lambda **kwargs: calls.append(kwargs))
    # Act + Assert
    assert tracing.init_tracing() is False
    assert calls == []


def test_start_span_records_a_named_span(
    captured_spans: InMemorySpanExporter,
) -> None:
    # Act
    with tracing.start_span("fetch_source") as span:
        span.end()
    # Assert
    spans = list(captured_spans.get_finished_spans())
    assert [span.name for span in spans] == ["fetch_source"]


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
