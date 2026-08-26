from collections.abc import Callable

import pytest

from config import (
    DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)


@pytest.mark.parametrize(
    ("env_var", "getter", "default", "valid", "expected", "bad", "range_bad"),
    [
        (
            "OPENAI_TIMEOUT_SECONDS",
            get_openai_timeout_seconds,
            DEFAULT_OPENAI_TIMEOUT_SECONDS,
            "12.5",
            12.5,
            "soon",
            "0",
        ),
        (
            "OPENAI_MAX_OUTPUT_TOKENS",
            get_openai_max_output_tokens,
            DEFAULT_OPENAI_MAX_OUTPUT_TOKENS,
            "2048",
            2048,
            "many",
            "0",
        ),
    ],
)
def test_env_accessors(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    getter: Callable[[], int | float],
    default: int | float,
    valid: str,
    expected: int | float,
    bad: str,
    range_bad: str,
) -> None:
    monkeypatch.delenv(env_var, raising=False)
    assert getter() == default
    monkeypatch.setenv(env_var, valid)
    assert getter() == expected
    monkeypatch.setenv(env_var, bad)
    assert getter() == default
    monkeypatch.setenv(env_var, range_bad)
    assert getter() == default
