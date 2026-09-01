"""The orchestrator agent's conversation state and routing schema."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import NotRequired

Destination = Literal["geopolitical", "other"]


class RouteDecision(BaseModel):
    """The classifier's structured output: where the turn goes, and as what.

    Both fields are required with no default, which is what
    `with_structured_output(..., strict=True)` needs.
    """

    destination: Destination = Field(
        description=(
            "'geopolitical' when the last user turn is a political or "
            "geopolitical question, 'other' for anything else."
        )
    )
    standalone_query: str = Field(
        description=(
            "The last user turn rewritten so it stands alone, with pronouns "
            "and elisions resolved from the conversation."
        )
    )


class OrchestratorState(TypedDict):
    """Conversation state. `messages` is the only accumulating channel.

    `destination` and `standalone_query` are `NotRequired` because a turn's
    input carries only the new human message; `classify` writes both before
    anything reads them. Seeding them with defaults instead would turn a
    classifier that failed to write `destination` into a silent fall-through
    to the chat branch.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    destination: NotRequired[Destination]
    standalone_query: NotRequired[str]


def build_initial_orchestrator_state(query: str) -> OrchestratorState:
    """Return the input for one turn: exactly one new human message.

    The `add_messages` reducer appends this to whatever the checkpointer
    already holds for the thread, so a turn never re-sends history.
    """
    normalized = " ".join((query or "").split())
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {"messages": [HumanMessage(normalized)]}
