import sys
import types

import pytest

import tracing


@pytest.fixture(autouse=True)
def _reset_initialized() -> None:
    tracing._initialized = False


def _install_fake_phoenix_otel(monkeypatch: pytest.MonkeyPatch, register: object) -> None:
    """Stub sys.modules so tests don't require the real package installed."""
    otel_module = types.ModuleType("phoenix.otel")
    otel_module.register = register  # type: ignore[attr-defined]
    phoenix_module = types.ModuleType("phoenix")
    phoenix_module.otel = otel_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix", phoenix_module)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel_module)


def test_init_tracing_noop_when_endpoint_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_swallows_register_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://unroutable.invalid:6006")

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("collector unreachable")

    _install_fake_phoenix_otel(monkeypatch, _boom)
    assert tracing.init_tracing() is False
    assert tracing._initialized is False


def test_init_tracing_registers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006")
    monkeypatch.setenv("PHOENIX_PROJECT_NAME", "test-project")
    calls: list[dict[str, object]] = []

    def _spy(**kwargs: object) -> None:
        calls.append(kwargs)

    _install_fake_phoenix_otel(monkeypatch, _spy)

    assert tracing.init_tracing() is True
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "http://phoenix:6006"
    assert calls[0]["project_name"] == "test-project"

    assert tracing.init_tracing() is False
    assert len(calls) == 1
