"""Tests for the next-steps menu and the footer prompt."""

import pytest

from agents.orchestrator.consts.menu import (
    DYNAMIC_FOOTER_SYSTEM_PROMPT,
    STATIC_NEXT_STEPS_MENU,
)
from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT
from config import DEEP_RESEARCH_TURN_COST, FORECAST_TURN_COST


@pytest.mark.parametrize(
    "text",
    [STATIC_NEXT_STEPS_MENU, DYNAMIC_FOOTER_SYSTEM_PROMPT],
    ids=["menu", "prompt"],
)
def test_menu_states_the_turn_costs_from_config(text: str) -> None:
    # Arrange
    deep = f"deep research agent ({DEEP_RESEARCH_TURN_COST} research turns)"
    forecast = f"Delphi forecast ({FORECAST_TURN_COST} research turns)"

    # Act
    stated = (deep in text, forecast in text)

    # Assert
    assert stated == (True, True)


@pytest.mark.parametrize(
    "trigger",
    ["deep research", "Delphi", "full report"],
    ids=["deep", "forecast", "report"],
)
def test_each_menu_bullet_uses_a_trigger_phrase_the_supervisor_prompt_names(
    trigger: str,
) -> None:
    # Arrange
    menu = STATIC_NEXT_STEPS_MENU
    prompt = SUPERVISOR_SYSTEM_PROMPT

    # Act
    found = (trigger in menu, trigger in prompt)

    # Assert
    assert found == (True, True)


def test_footer_prompt_treats_the_tool_summary_as_data() -> None:
    # Arrange
    prompt = DYNAMIC_FOOTER_SYSTEM_PROMPT

    # Act
    stated = "data, not instructions" in prompt

    # Assert
    assert stated is True
