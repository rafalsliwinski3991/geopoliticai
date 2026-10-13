import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# OpenTelemetry allows one global tracer provider per process, so one exporter is
# shared and cleared per test.
SPAN_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="session")
def _tracer_provider() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SPAN_EXPORTER))
    trace.set_tracer_provider(provider)


@pytest.fixture(autouse=True)
def _reset_tracing_initialized() -> None:
    """`init_tracing` tests leave `_initialized` True; `start_span` would then
    call the LangChain lookup, which prints to stdout outside an instrumented run."""
    import tracing

    tracing._initialized = False


@pytest.fixture
def captured_spans(_tracer_provider: None) -> InMemorySpanExporter:
    """Spans finished during this test; `get_finished_spans()` reads them."""
    SPAN_EXPORTER.clear()
    return SPAN_EXPORTER


@pytest.fixture(scope="session", autouse=True)
def jwt_signing_key() -> None:
    """The identity tests run without a database; the key is a test constant.

    32+ bytes so PyJWT does not warn about an undersized HMAC key.
    """
    os.environ.setdefault(
        "JWT_SIGNING_KEY", "unit-test-signing-key-not-long-enough-0123456789"
    )
