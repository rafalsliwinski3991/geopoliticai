"""The orchestrator agent's conversation state and routing schema."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict

Destination = Literal["geopolitical", "deep", "forecast", "other", "report"]


class GeopoliticState(TypedDict):
    """The multi-agent orchestrator shared workspace state.

    Specialist agent outputs (sources, synthesis, forecast, report draft) accumulate
    in dedicated channels alongside conversation messages.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    destination: NotRequired[Destination]
    standalone_query: NotRequired[str]
    retrieved_sources: NotRequired[list[dict[str, str]]]
    expert_synthesis: NotRequired[list[str]]
    forecast_data: NotRequired[list[dict[str, Any]]]
    report_draft: NotRequired[str | None]


# Backward compatibility alias
OrchestratorState = GeopoliticState


def build_initial_orchestrator_state(query: str) -> GeopoliticState:
    """Return the input for one turn: exactly one new human message.

    The `add_messages` reducer appends this to whatever the checkpointer
    already holds for the thread, so a turn never re-sends history.
    """
    normalized = " ".join((query or "").split())
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {"messages": [HumanMessage(normalized)]}
