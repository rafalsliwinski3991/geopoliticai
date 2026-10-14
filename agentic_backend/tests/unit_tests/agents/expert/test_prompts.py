"""The expert's answer prompt ends with a fixed next-step menu."""

import api
from agents.expert.prompts import (
    ANSWER_SYSTEM_PROMPT,
    NEXT_STEPS_MENU,
    REPORT_TURN_COST,
)
from agents.orchestrator.prompts import CLASSIFY_SYSTEM_PROMPT
from config import DAILY_RESEARCH_TURNS, DEEP_RESEARCH_TURN_COST, FORECAST_TURN_COST


def test_answer_prompt_states_costs_from_config() -> None:
    # Arrange
    options = [
        (
            "Do a deep dive on",
            f"Uses {DEEP_RESEARCH_TURN_COST} of your {DAILY_RESEARCH_TURNS} daily research turns",
        ),
        (
            "Forecast whether",
            f"Needs all {FORECAST_TURN_COST} of your {DAILY_RESEARCH_TURNS}",
        ),
        (
            "Write me a report on this conversation",
            f"Uses {REPORT_TURN_COST} of your {DAILY_RESEARCH_TURNS} daily research turns",
        ),
    ]

    # Act
    missing = [
        trigger
        for trigger, cost_phrase in options
        if not any(
            trigger in line and cost_phrase in line
            for line in NEXT_STEPS_MENU.splitlines()
        )
    ]

    # Assert
    assert missing == []


def test_answer_prompt_names_router_trigger_phrases() -> None:
    # Arrange
    triggers = [
        "Do a deep dive on",
        "Forecast whether",
        "Write me a report on this conversation",
    ]
    router_cores = ["deep dive", "forecast whether", "write me a report"]

    # Act
    missing = [trigger for trigger in triggers if trigger not in ANSWER_SYSTEM_PROMPT]
    unroutable = [
        core for core in router_cores if core not in CLASSIFY_SYSTEM_PROMPT.lower()
    ]

    # Assert
    assert missing == []
    assert unroutable == []


def test_answer_prompt_has_no_unfilled_braces() -> None:
    # Arrange
    braces_chars = "{}"

    # Act
    braces = [char for char in ANSWER_SYSTEM_PROMPT if char in braces_chars]

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


def test_answer_prompt_ends_with_rule_5_directive_then_menu() -> None:
    # Arrange
    directive = "End every answer with a horizontal rule (`---`)"

    # Act
    directive_index = ANSWER_SYSTEM_PROMPT.index(directive)
    menu_index = ANSWER_SYSTEM_PROMPT.index(NEXT_STEPS_MENU)

    # Assert
    assert directive_index < menu_index


def test_report_turn_cost_matches_api_one_unit() -> None:
    # Arrange
    stated_cost = REPORT_TURN_COST

    # Act
    api_cost = api.ONE_UNIT[0]

    # Assert
    assert api_cost == stated_cost


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
