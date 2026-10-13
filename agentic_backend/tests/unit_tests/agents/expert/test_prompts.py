"""The expert's answer prompt ends with a fixed next-step menu."""

from agents.expert.prompts import (
    ANSWER_SYSTEM_PROMPT,
    NEXT_STEPS_MENU,
    REPORT_TURN_COST,
)
from config import DAILY_RESEARCH_TURNS, DEEP_RESEARCH_TURN_COST, FORECAST_TURN_COST


def test_answer_prompt_states_costs_from_config() -> None:
    # Arrange
    costs = {
        DEEP_RESEARCH_TURN_COST,
        FORECAST_TURN_COST,
        REPORT_TURN_COST,
    }

    # Act
    found = {
        cost: f"Uses {cost} of your {DAILY_RESEARCH_TURNS} daily research turns"
        in ANSWER_SYSTEM_PROMPT
        for cost in costs
    }

    # Assert
    assert found == {
        DEEP_RESEARCH_TURN_COST: True,
        FORECAST_TURN_COST: True,
        REPORT_TURN_COST: True,
    }


def test_answer_prompt_names_router_trigger_phrases() -> None:
    # Arrange
    triggers = [
        "Do a deep dive on",
        "Forecast whether",
        "Write me a report on this conversation",
    ]

    # Act
    missing = [trigger for trigger in triggers if trigger not in ANSWER_SYSTEM_PROMPT]

    # Assert
    assert missing == []


def test_answer_prompt_has_no_unfilled_braces() -> None:
    # Act
    braces = [char for char in ANSWER_SYSTEM_PROMPT if char in "{}"]

    # Assert
    assert braces == []


def test_answer_prompt_exempts_menu_from_source_rules() -> None:
    # Arrange
    exemption_phrase = "except the closing menu in rule 5"
    exemption_rules = "rules 1 to 3 do not apply to it"

    # Act
    in_rule_4 = exemption_phrase in ANSWER_SYSTEM_PROMPT
    in_rule_5 = exemption_rules in ANSWER_SYSTEM_PROMPT

    # Assert
    assert in_rule_4
    assert in_rule_5


def test_next_steps_menu_has_no_links() -> None:
    # Arrange

    # Act
    markdown_links = "](" in NEXT_STEPS_MENU
    urls = "http" in NEXT_STEPS_MENU
    menu_in_prompt = NEXT_STEPS_MENU in ANSWER_SYSTEM_PROMPT

    # Assert
    assert not markdown_links
    assert not urls
    assert menu_in_prompt
