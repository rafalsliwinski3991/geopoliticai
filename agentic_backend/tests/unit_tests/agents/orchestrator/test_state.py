import pytest
from langchain_core.messages import HumanMessage
from pydantic import Field, ValidationError, create_model

from agents.orchestrator.state import (
    Destination,
    RouteDecision,
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


def test_a_route_decision_arrives_with_its_query_squashed() -> None:
    # Arrange
    raw = {"destination": "other", "standalone_query": "  and \n Poland?  "}

    # Act
    decision = RouteDecision.model_validate(raw)

    # Assert
    assert decision.standalone_query == "and Poland?"


def test_route_decision_rejects_unknown_destination() -> None:
    # Act + Assert
    with pytest.raises(ValidationError):
        RouteDecision.model_validate(
            {"destination": "unknown", "standalone_query": "question"}
        )
    assert (
        RouteDecision.model_validate(
            {"destination": "report", "standalone_query": "question"}
        ).destination
        == "report"
    )
    assert (
        RouteDecision.model_validate(
            {"destination": "deep", "standalone_query": "question"}
        ).destination
        == "deep"
    )
    assert (
        RouteDecision.model_validate(
            {"destination": "forecast", "standalone_query": "question"}
        ).destination
        == "forecast"
    )


def test_the_route_schema_is_a_plain_string_field() -> None:
    # Arrange
    # The strict structured-output call sends this schema to the model. A twin
    # with plain `str` fields must produce the same schema, or the annotation
    # changed what the model is asked for.
    plain = create_model(
        "PlainRouteDecision",
        __doc__=RouteDecision.__doc__,
        destination=(
            Destination,
            Field(description=RouteDecision.model_fields["destination"].description),
        ),
        standalone_query=(
            str,
            Field(
                description=RouteDecision.model_fields["standalone_query"].description
            ),
        ),
    )

    # Act
    schema = RouteDecision.model_json_schema()
    twin = plain.model_json_schema()

    # Assert
    del schema["title"], twin["title"]
    assert schema == twin
