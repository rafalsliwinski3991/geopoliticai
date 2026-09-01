"""Graph construction for the orchestrator agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.orchestrator.nodes import chat, classify, expert
from agents.orchestrator.state import OrchestratorState
from tracing import init_tracing


def _route(state: OrchestratorState) -> str:
    """Read the branch `classify` already decided; decide nothing here."""
    return state["destination"]


def build_graph(checkpointer: Any | None = None) -> Any:
    """Construct and compile the orchestrator graph.

    The checkpointer is an argument and is never built here. `graph.py`
    constructs and never runs, `make test` and `langgraph dev` must keep
    working with no database, and the hard `DATABASE_URL` requirement belongs
    to the API lifespan, which is the only caller that passes a real saver.
    """
    orchestrator = StateGraph(OrchestratorState)
    orchestrator.add_node("classify", classify)
    orchestrator.add_node("expert", expert)
    orchestrator.add_node("chat", chat)
    orchestrator.add_edge(START, "classify")
    orchestrator.add_conditional_edges(
        "classify", _route, {"geopolitical": "expert", "other": "chat"}
    )
    orchestrator.add_edge("expert", END)
    orchestrator.add_edge("chat", END)
    return orchestrator.compile(name="orchestrator", checkpointer=checkpointer)


def build_runtime_config(*, thread_id: str) -> dict[str, dict[str, Any]]:
    """Build runtime configuration for one conversation turn.

    Unlike the expert's, `thread_id` is required, not optional: a checkpointed
    graph has no meaning without the thread it checkpoints into.
    """
    if not thread_id.strip():
        raise ValueError("thread_id must not be empty.")
    return {"configurable": {"thread_id": thread_id}}


# Same reason as `agents/expert/graph.py`: `langgraph dev` imports this module
# and nothing else, so module scope is Studio's only hook for Phoenix tracing.
# `init_tracing()` is idempotent and never raises.
init_tracing()
graph = build_graph()
