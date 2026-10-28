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
