"""Graph construction for the expert agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.expert.nodes import answer, search_and_fetch
from agents.expert.state import PipelineState
from tracing import init_tracing


def build_graph() -> Any:
    """Construct and compile the two-node LangGraph pipeline."""
    pipeline = StateGraph(PipelineState)
    pipeline.add_node("search_and_fetch", search_and_fetch)
    pipeline.add_node("answer", answer)
    pipeline.add_edge(START, "search_and_fetch")
    pipeline.add_edge("search_and_fetch", "answer")
    pipeline.add_edge("answer", END)
    return pipeline.compile(name="expert")


def build_runtime_config(*, thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Build runtime configuration shared by entrypoints."""
    configurable: dict[str, Any] = {}
    if thread_id is not None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty when provided.")
        configurable["thread_id"] = thread_id
    return {"configurable": configurable}


# `langgraph dev` imports this module and nothing else, so module scope is
# Studio's only hook for Phoenix tracing. `init_tracing()` is idempotent and
# never raises, so this is not orchestration leaking back into construction.
init_tracing()
graph = build_graph()
