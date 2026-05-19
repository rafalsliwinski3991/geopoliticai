import logging
from collections.abc import Callable

import pytest

from geopoliticai.config import (
    DEFAULT_ANALYST_ADDITIONAL_SOURCES,
    DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    get_analyst_additional_sources,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)


@pytest.mark.parametrize(
    (
        "env_var",
        "getter",
        "default_value",
        "valid_raw",
        "valid_value",
        "malformed_raw",
        "parse_warning",
        "range_raw",
        "range_warning",
        "fallback_text",
    ),
    [
        (
            "ANALYST_ADDITIONAL_SOURCES",
            get_analyst_additional_sources,
            DEFAULT_ANALYST_ADDITIONAL_SOURCES,
            " 3 ",
            3,
            "many",
            "expected an integer",
            "-1",
            "expected a non-negative integer",
            "Falling back to 0.",
        ),
        (
            "OPENAI_TIMEOUT_SECONDS",
            get_openai_timeout_seconds,
            DEFAULT_OPENAI_TIMEOUT_SECONDS,
            " 12.5 ",
            12.5,
            "soon",
            "expected a float",
            "0",
            "expected a positive float",
            "Falling back to 60.00.",
        ),
        (
            "OPENAI_MAX_OUTPUT_TOKENS",
            get_openai_max_output_tokens,
            DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
            " 2048 ",
            2048,
            "many",
            "expected an integer",
            "0",
            "expected a positive integer",
            "Falling back to 4096.",
        ),
    ],
)
def test_env_config_accessors_preserve_parsing_behavior(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    env_var: str,
    getter: Callable[[], int | float],
    default_value: int | float,
    valid_raw: str,
    valid_value: int | float,
    malformed_raw: str,
    parse_warning: str,
    range_raw: str,
    range_warning: str,
    fallback_text: str,
) -> None:
    caplog.set_level(logging.WARNING, logger="geopoliticai.config")

    monkeypatch.delenv(env_var, raising=False)
    assert getter() == default_value
    assert not caplog.records

    monkeypatch.setenv(env_var, "   ")
    assert getter() == default_value
    assert not caplog.records

    monkeypatch.setenv(env_var, valid_raw)
    assert getter() == valid_value
    assert not caplog.records

    monkeypatch.setenv(env_var, malformed_raw)
    assert getter() == default_value
    assert f"Invalid {env_var}={malformed_raw!r}; {parse_warning}." in caplog.text
    assert fallback_text in caplog.text

    caplog.clear()
    monkeypatch.setenv(env_var, range_raw)
    assert getter() == default_value
    assert f"Invalid {env_var}={range_raw!r}; {range_warning}." in caplog.text
    assert fallback_text in caplog.text
