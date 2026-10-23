"""The orchestrator agent's conversation state and routing schema."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

from models import CleanText, squash_whitespace

Destination = Literal["geopolitical", "deep", "forecast", "other", "report"]


class RouteDecision(BaseModel):
    """The classifier's structured output: where the turn goes, and as what.

    Both fields are required with no default, which is what
    `with_structured_output(..., strict=True)` needs.
    """

    destination: Destination = Field(
        description=(
            "The complete set of destinations is 'geopolitical', 'deep', "
            "'forecast', 'report', 'other' — pick exactly one of those five, "
            "never anything outside it. Choose 'geopolitical' when the last "
            "user turn is a political or geopolitical question, 'deep' when it "
            "is one and the user has explicitly asked for an in-depth answer on "
            "this topic, 'forecast' when the last user turn itself explicitly "
            "asks for a forecast or a prediction, 'report' when it asks for a "
            "written report or write-up of what has already been discussed, "
            "'other' for anything else."
        )
    )
    standalone_query: CleanText = Field(
        description=(
            "The last user turn rewritten so it stands alone, with pronouns "
            "and elisions resolved from the conversation."
        )
    )


class OrchestratorState(TypedDict):
    """The orchestrator's conversation state.

    The specialist tools write their synthesis and forecasts into dedicated
    channels beside the messages; the reporter reads them to know whether any
    researched material exists.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    destination: NotRequired[Destination]
    standalone_query: NotRequired[str]
    expert_synthesis: NotRequired[list[str]]
    forecast_data: NotRequired[list[dict[str, Any]]]


def build_initial_orchestrator_state(query: str) -> OrchestratorState:
    """Return the input for one turn: exactly one new human message.

    The `add_messages` reducer appends this to whatever the checkpointer
    already holds for the thread, so a turn never re-sends history.
    """
    normalized = squash_whitespace(query or "")
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {"messages": [HumanMessage(normalized)]}
