import contextvars
import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from config import (
    _REPO_ROOT_ENV,
    DAILY_RESEARCH_TURNS,
    DAILY_RESEARCH_TURNS_ALL_USERS,
    DEEP_RESEARCH_TURN_COST,
    DEFAULT_LLM_SETTINGS,
    LLMSettings,
    LogContextFilter,
    bind_log_context,
    get_arize_platform,
    get_trace_endpoint,
    init_environment,
)

NOISY_LOGGERS = ("httpx", "httpcore", "openai", "urllib3")


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


def _record() -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)


def test_log_filter_uses_placeholders_when_unbound() -> None:
    # Arrange
    record = _record()

    # Act
    kept = contextvars.copy_context().run(LogContextFilter().filter, record)

    # Assert
    assert kept is True
    assert record.thread_id == "-"  # type: ignore[attr-defined]
    assert record.user_id == "-"  # type: ignore[attr-defined]


def test_log_filter_stamps_bound_ids() -> None:
    # Arrange
    record = _record()

    def run() -> None:
        bind_log_context(thread_id="t-1", user_id=7)
        LogContextFilter().filter(record)

    # Act
    contextvars.copy_context().run(run)

    # Assert
    assert record.thread_id == "t-1"  # type: ignore[attr-defined]
    assert record.user_id == 7  # type: ignore[attr-defined]


@pytest.fixture
def restore_root_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr("config.load_dotenv", lambda *args, **kwargs: None)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    noisy = {name: logging.getLogger(name).level for name in NOISY_LOGGERS}
    yield
    for name, noisy_level in noisy.items():
        logging.getLogger(name).setLevel(noisy_level)
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_init_environment_formats_every_line_with_the_context(
    restore_root_logging: None,
) -> None:
    # Arrange
    init_environment()
    stream = io.StringIO()
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(stream)

    def run() -> None:
        bind_log_context(thread_id="t-1", user_id=7)
        logging.getLogger("search").warning("hello there")

    # Act
    contextvars.copy_context().run(run)

    # Assert
    line = stream.getvalue()
    assert "search" in line
    assert "[thread=t-1 user=7]" in line
    assert "hello there" in line


def test_deep_cost_fits_inside_the_daily_quota() -> None:
    # Assert: pins §4.2's unchecked first-insert branch — the advisory headroom
    # read and the site ceiling stay safe only while the cost fits both limits.
    assert (
        1
        < DEEP_RESEARCH_TURN_COST
        <= min(DAILY_RESEARCH_TURNS, DAILY_RESEARCH_TURNS_ALL_USERS)
    )
