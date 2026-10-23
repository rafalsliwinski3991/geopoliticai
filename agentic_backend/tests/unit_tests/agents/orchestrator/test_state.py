"""Tests for the orchestrator agent's conversation state schema and configuration."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.orchestrator.config import (
    FOOTER_LLM_SETTINGS,
    SUPERVISOR_LLM_SETTINGS,
)
from agents.orchestrator.consts.menu import (
    DYNAMIC_FOOTER_SYSTEM_PROMPT,
    STATIC_NEXT_STEPS_MENU,
)
from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT
from agents.orchestrator.state import (
    GeopoliticState,
    OrchestratorState,
    build_initial_orchestrator_state,
)


def test_build_initial_state_normalizes_one_human_message() -> None:
    # Act
    state = build_initial_orchestrator_state("  what   is\n happening? ")

    # Assert
    assert state == {"messages": [HumanMessage("what is happening?")]}
    assert "destination" not in state
    assert "standalone_query" not in state


@pytest.mark.parametrize("query", ["", " \t\n"])
def test_build_initial_state_rejects_empty_query(query: str) -> None:
    # Act + Assert
    with pytest.raises(ValueError):
        build_initial_orchestrator_state(query)


def test_geopolitic_state_is_orchestrator_state_alias() -> None:
    """OrchestratorState is preserved as a backward compatibility alias.

    Existing modules import OrchestratorState while transitioning to supervisor.
    """
    # Arrange
    canonical_type = GeopoliticState

    # Act
    alias_type = OrchestratorState

    # Assert
    assert alias_type is canonical_type


def test_geopolitic_state_accepts_all_workspace_channels() -> None:
    """Specialist tools write into shared workspace channels.

    GeopoliticState must declare messages, destination, retrieved_sources,
    expert_synthesis, forecast_data, and report_draft.
    """
    # Arrange
    sample_sources = [{"title": "Treaty of Rome", "url": "https://example.com/rome"}]
    sample_synthesis = ["European integration began with the EEC."]
    sample_forecast = [{"scenario": "expansion", "probability": 0.75}]
    sample_report = "# Summary Report\nContent goes here."

    # Act
    state: GeopoliticState = {
        "messages": [HumanMessage("Analyze treaties"), AIMessage("Researching...")],
        "destination": "geopolitical",
        "standalone_query": "Analyze treaties",
        "retrieved_sources": sample_sources,
        "expert_synthesis": sample_synthesis,
        "forecast_data": sample_forecast,
        "report_draft": sample_report,
    }

    # Assert
    assert len(state["messages"]) == 2
    assert state.get("destination") == "geopolitical"
    assert state.get("retrieved_sources") == sample_sources
    assert state.get("expert_synthesis") == sample_synthesis
    assert state.get("forecast_data") == sample_forecast
    assert state.get("report_draft") == sample_report


def test_build_initial_orchestrator_state_omits_workspace_channels() -> None:
    """Initial state must only contain the user message.

    Seeding empty workspace channels would clobber accumulated state in the reducer.
    """
    # Arrange
    query = "Summarize the current situation"

    # Act
    state = build_initial_orchestrator_state(query)

    # Assert
    assert state == {"messages": [HumanMessage("Summarize the current situation")]}
    assert "retrieved_sources" not in state
    assert "expert_synthesis" not in state
    assert "forecast_data" not in state
    assert "report_draft" not in state


def test_supervisor_config_defines_supervisor_and_footer_settings() -> None:
    """Supervisor routing and dynamic footer generation require deterministic low-temperature model configurations.

    Without bounded token limits and deterministic temperature, routing and footer generation
    can hallucinate or exceed latency budgets.
    """
    # Arrange
    expected_model = "gpt-5-mini"
    expected_temperature = 0.0
    expected_footer_max_tokens = 250

    # Act
    supervisor_settings = SUPERVISOR_LLM_SETTINGS
    footer_settings = FOOTER_LLM_SETTINGS

    # Assert
    assert supervisor_settings.model == expected_model
    assert supervisor_settings.temperature == expected_temperature
    assert footer_settings.model == expected_model
    assert footer_settings.temperature == expected_temperature
    assert footer_settings.max_output_tokens == expected_footer_max_tokens


def test_static_next_steps_menu_and_footer_prompt_define_expected_turns() -> None:
    """Static and dynamic menus must offer consistent turn costs.

    The costs across follow-up, deep expert, forecaster, and reporter must match
    the product turn specifications (0, 4, 8, 1).
    """
    # Arrange
    expected_follow_up = "Ask a follow-up (0 research turns)"
    expected_deep = "Explore in depth with the deep research agent (4 research turns)"
    expected_forecast = "Generate a Delphi forecast (8 research turns)"
    expected_report = "Generate a comprehensive report (1 research turn)"

    # Act
    static_menu = STATIC_NEXT_STEPS_MENU
    dynamic_prompt = DYNAMIC_FOOTER_SYSTEM_PROMPT

    # Assert
    assert expected_follow_up in static_menu
    assert expected_deep in static_menu
    assert expected_forecast in static_menu
    assert expected_report in static_menu
    assert "**What next?**" in dynamic_prompt
    assert "4 research turns" in dynamic_prompt
    assert "8 research turns" in dynamic_prompt
    assert "1 research turn" in dynamic_prompt


def test_supervisor_system_prompt_defines_specialist_tools_and_rules() -> None:
    """Supervisor prompt must specify the 4 specialist tools and rules.

    The prompt directs routing to run_expert, run_deep_expert, run_deep_forecaster,
    and run_reporter, with clear instructions for direct responses and standalone rewrites.
    """
    # Arrange
    required_tools = [
        "run_expert",
        "run_deep_expert",
        "run_deep_forecaster",
        "run_reporter",
    ]

    # Act
    prompt_text = SUPERVISOR_SYSTEM_PROMPT

    # Assert
    for tool_name in required_tools:
        assert tool_name in prompt_text
    assert "small-talk question" in prompt_text
    assert "standalone queries" in prompt_text
