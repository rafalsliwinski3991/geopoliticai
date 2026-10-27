"""The orchestrator agent's conversation state."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict

from shared.text import squash_whitespace

Destination = Literal["geopolitical", "deep", "forecast", "other", "report"]


class OrchestratorState(TypedDict):
    """The orchestrator's conversation state.

    The specialist tools write their synthesis and forecasts into dedicated
    channels beside the messages; the reporter reads them to know whether any
    researched material exists.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    destination: NotRequired[Destination]
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
