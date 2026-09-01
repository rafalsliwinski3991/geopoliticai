import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from agents.orchestrator.state import (
    RouteDecision,
    build_initial_orchestrator_state,
)


def test_build_initial_state_normalizes_one_human_message() -> None:
    state = build_initial_orchestrator_state("  what   is\n happening? ")

    assert state == {"messages": [HumanMessage("what is happening?")]}
    assert "destination" not in state
    assert "standalone_query" not in state


@pytest.mark.parametrize("query", ["", " \t\n"])
def test_build_initial_state_rejects_empty_query(query: str) -> None:
    with pytest.raises(ValueError):
        build_initial_orchestrator_state(query)


def test_route_decision_rejects_unknown_destination() -> None:
    with pytest.raises(ValidationError):
        RouteDecision.model_validate(
            {"destination": "unknown", "standalone_query": "question"}
        )
