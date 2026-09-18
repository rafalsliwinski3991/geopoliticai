from pathlib import Path

import pytest

from config import (
    _REPO_ROOT_ENV,
    DEFAULT_LLM_SETTINGS,
    LLMSettings,
    get_arize_platform,
    get_trace_endpoint,
)


def test_arize_platform_defaults_to_phoenix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARIZE_PLATFORM", raising=False)

    assert get_arize_platform() == "PHOENIX"


def test_arize_platform_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIZE_PLATFORM", "datadog")

    with pytest.raises(ValueError, match="ARIZE_PLATFORM must be one of AX, PHOENIX"):
        get_arize_platform()


def test_trace_endpoint_uses_ax_for_ax_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARIZE_PLATFORM", "AX")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "http://ax/v1/traces")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix/v1/traces")

    assert get_trace_endpoint() == "http://ax/v1/traces"


def test_trace_endpoint_uses_phoenix_for_phoenix_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARIZE_PLATFORM", "PHOENIX")
    monkeypatch.setenv("ARIZE_COLLECTOR_ENDPOINT", "http://ax/v1/traces")
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix/v1/traces")

    assert get_trace_endpoint() == "http://phoenix/v1/traces"


def test_default_llm_settings_values() -> None:
    # Assert
    assert DEFAULT_LLM_SETTINGS.model == "gpt-4o-mini"
    assert DEFAULT_LLM_SETTINGS.temperature == 0.0
    assert DEFAULT_LLM_SETTINGS.timeout_seconds == 60.0
    assert DEFAULT_LLM_SETTINGS.max_output_tokens == 16_384


def test_llm_settings_is_overridable_per_call_site() -> None:
    # Act
    overridden = LLMSettings(
        model="gpt-4o", temperature=0.7, timeout_seconds=30.0, max_output_tokens=1024
    )
    # Assert
    assert overridden.model == "gpt-4o"
    assert overridden.temperature == 0.7
    assert overridden.timeout_seconds == 30.0
    assert overridden.max_output_tokens == 1024
    assert DEFAULT_LLM_SETTINGS.model == "gpt-4o-mini"


def test_repo_root_env_resolves_to_the_repo_root() -> None:
    """The rename moved the directory, not its depth: .env stays at the repo root.

    A rename that changes the nesting depth of `src/config.py` would otherwise
    break every entrypoint's environment loading silently.
    """
    assert _REPO_ROOT_ENV == Path(__file__).resolve().parents[3] / ".env"
