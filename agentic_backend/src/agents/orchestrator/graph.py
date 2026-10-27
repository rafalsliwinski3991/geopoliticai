"""Graph construction for the supervisor orchestrator agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.store.base import BaseStore

from agents.orchestrator.nodes.supervisor import supervisor
from agents.orchestrator.state import OrchestratorState
from agents.orchestrator.tools import ALL_TOOLS
from shared.tracing import init_tracing


def _route_after_tools(state: OrchestratorState) -> str:
    # run_reporter goes straight to END on completion or cancellation
    if state.get("destination") == "report":
        return END
    return "supervisor"


def build_graph(checkpointer: Any | None = None, store: BaseStore | None = None) -> Any:
    """Construct and compile the supervisor orchestrator graph.

    The checkpointer and the store are arguments and are never built here.
    `graph.py` constructs and never runs, `make test` and `langgraph dev` must
    keep working with no database, and the hard `DATABASE_URL` requirement
    belongs to the API lifespan, which is the only caller that passes a real
    saver and a real store. The store reaches every tool as `runtime.store`
    (the deep forecaster's video-notes cache).

    `handle_tool_errors=False` lets every tool failure, a malformed tool call
    included, raise to the API's error frame and its refund. The default would
    turn a malformed call into an error ToolMessage that nothing retries.
    """
    orchestrator = StateGraph(OrchestratorState)
    orchestrator.add_node("supervisor", supervisor)
    orchestrator.add_node("tools", ToolNode(ALL_TOOLS, handle_tool_errors=False))

    orchestrator.add_edge(START, "supervisor")
    orchestrator.add_conditional_edges(
        "supervisor",
        tools_condition,
        {"tools": "tools", END: END},
    )
    orchestrator.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"supervisor": "supervisor", END: END},
    )

    return orchestrator.compile(
        name="orchestrator", checkpointer=checkpointer, store=store
    )


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
