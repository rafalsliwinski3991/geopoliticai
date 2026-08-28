"""Graph construction and execution for the expert agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agents.expert.nodes import answer, search_and_fetch
from agents.expert.state import PipelineState, build_initial_pipeline_state
from models import LLMInvocationError
from tracing import init_tracing

NODE_LABELS: dict[str, str] = {
    "search_and_fetch": "Searching and reading sources...",
    "answer": "Writing the answer...",
}
PipelineEvent = tuple[Literal["progress", "token"], str]


def build_graph() -> Any:
    """Construct and compile the two-node LangGraph pipeline."""
    pipeline = StateGraph(PipelineState)
    pipeline.add_node("search_and_fetch", search_and_fetch)
    pipeline.add_node("answer", answer)
    pipeline.add_edge(START, "search_and_fetch")
    pipeline.add_edge("search_and_fetch", "answer")
    pipeline.add_edge("answer", END)
    return pipeline.compile(name="expert")


init_tracing()
graph = build_graph()


def build_runtime_config(*, thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Build runtime configuration shared by entrypoints."""
    configurable: dict[str, Any] = {}
    if thread_id is not None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty when provided.")
        configurable["thread_id"] = thread_id
    return {"configurable": configurable}


def _chunk_text(chunk: object) -> str:
    """Extract text from a streamed LangChain content chunk."""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            parts.append(block["text"])
    return "".join(parts)


async def astream_pipeline(
    query: str, *, thread_id: str | None = None
) -> AsyncIterator[PipelineEvent]:
    """Run one request, yielding progress and answer-token events."""
    state = build_initial_pipeline_state(query)
    config = build_runtime_config(thread_id=thread_id)
    seen_nodes: set[str] = set()
    async for event in graph.astream_events(state, config=config, version="v2"):
        event_type = event.get("event", "")
        metadata = event.get("metadata", {})
        node = metadata.get("langgraph_node", "") if isinstance(metadata, dict) else ""
        if (
            event_type == "on_chain_start"
            and node in NODE_LABELS
            and node not in seen_nodes
        ):
            seen_nodes.add(node)
            yield ("progress", node)
        elif event_type == "on_chat_model_stream" and node == "answer":
            text = _chunk_text(event.get("data", {}).get("chunk"))
            if text:
                yield ("token", text)


async def run_pipeline(query: str, *, thread_id: str | None = None) -> str:
    """Run the streaming path and return the complete answer."""
    parts: list[str] = []
    async for kind, text in astream_pipeline(query, thread_id=thread_id):
        if kind == "token":
            parts.append(text)
    result = "".join(parts).strip()
    if not result:
        raise LLMInvocationError("Pipeline produced no answer text.")
    return result
