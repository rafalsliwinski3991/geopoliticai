"""Tests for the orchestrator agent's conversation state."""

import pytest
from langchain_core.messages import HumanMessage

from agents.orchestrator.state import build_initial_orchestrator_state


def test_build_initial_state_normalizes_one_human_message() -> None:
    # Act
    state = build_initial_orchestrator_state("  what   is\n happening? ")

    # Assert
    assert state == {"messages": [HumanMessage("what is happening?")]}


@pytest.mark.parametrize("query", ["", " \t\n"])
def test_build_initial_state_rejects_empty_query(query: str) -> None:
    # Act + Assert
    with pytest.raises(ValueError):
        build_initial_orchestrator_state(query)


def test_build_initial_orchestrator_state_omits_workspace_channels() -> None:
    """Initial state must only contain the user message.

    Seeding empty workspace channels would clobber accumulated state in the reducer.
    """
    # Act
    state = build_initial_orchestrator_state("Summarize the current situation")

    # Assert
    assert state == {"messages": [HumanMessage("Summarize the current situation")]}
