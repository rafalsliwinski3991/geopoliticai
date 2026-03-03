from __future__ import annotations

from geopoliticai import config


def test_compose_final_model_is_valid_default() -> None:
    assert config.get_model("compose_final") == "gpt-4o"


def test_get_openai_timeout_seconds_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")
    assert config.get_openai_timeout_seconds() == 12.5


def test_get_openai_timeout_seconds_falls_back_for_invalid(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "0")
    assert config.get_openai_timeout_seconds() == config.DEFAULT_OPENAI_TIMEOUT_SECONDS


def test_get_openai_max_output_tokens_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "777")
    assert config.get_openai_max_output_tokens() == 777


def test_get_openai_max_output_tokens_falls_back_for_invalid(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "0")
    assert (
        config.get_openai_max_output_tokens()
        == config.DEFAULT_OPENAI_MAX_OUTPUT_TOKENS
    )
