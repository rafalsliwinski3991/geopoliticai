"""Tests for the orchestrator's own config."""

import pytest

from agents.orchestrator.config import FOOTER_LLM_SETTINGS, SUPERVISOR_LLM_SETTINGS
from shared.config import LLMSettings


@pytest.mark.parametrize(
    "settings",
    [SUPERVISOR_LLM_SETTINGS, FOOTER_LLM_SETTINGS],
    ids=["supervisor", "footer"],
)
def test_gpt_5_settings_ask_for_the_only_temperature_the_model_accepts(
    settings: LLMSettings,
) -> None:
    # Arrange
    model = settings.model

    # Act
    temperature = settings.temperature

    # Assert
    assert (model, temperature) == ("gpt-5-mini", 1.0)


def test_footer_settings_leave_room_for_reasoning_and_the_reply() -> None:
    """At 250 tokens the reasoning used them all and the reply came back empty."""
    # Arrange
    minimum = 1_000

    # Act
    ceiling = FOOTER_LLM_SETTINGS.max_output_tokens

    # Assert
    assert ceiling >= minimum
