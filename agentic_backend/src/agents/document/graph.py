"""Graph construction for the document agent."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.document.nodes import answer, retrieve
from agents.document.state import (
    DocumentContext,
    DocumentSearch,
    DocumentState,
    build_initial_document_state,
)
from shared.tracing import init_tracing


def build_graph() -> Any:
    """Construct and compile the two-node LangGraph pipeline."""
    pipeline = StateGraph(DocumentState, context_schema=DocumentContext)
    pipeline.add_node("retrieve", retrieve)
    pipeline.add_node("answer", answer)
    pipeline.add_edge(START, "retrieve")
    pipeline.add_edge("retrieve", "answer")
    pipeline.add_edge("answer", END)
    return pipeline.compile(name="document")


# `langgraph dev` imports this module and nothing else, so module scope is
# Studio's only hook for Phoenix tracing.
init_tracing()
graph = build_graph()


async def ask_document(
    query: str, history: list[str], search: DocumentSearch
) -> dict[str, Any]:
    """Answer `query` from the thread's document and return the final state."""
    result: dict[str, Any] = await graph.ainvoke(
        build_initial_document_state(query, history),
        context=DocumentContext(search=search),
    )
    return result
