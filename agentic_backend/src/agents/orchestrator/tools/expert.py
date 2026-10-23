"""Specialist tool: allow-listed expert research."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.expert import build_initial_pipeline_state
from agents.expert import graph as expert_graph
from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.orchestrator.state import GeopoliticState


def _source_to_dict(s: Any) -> dict[str, str]:
    if isinstance(s, dict):
        return {"title": str(s.get("title", "")), "url": str(s.get("url", ""))}
    return {"title": str(getattr(s, "title", "")), "url": str(getattr(s, "url", ""))}


@tool
async def run_expert(
    query: str, runtime: ToolRuntime[Any, GeopoliticState]
) -> Command[Any]:
    """Search allow-listed sources and synthesize a verified geopolitical answer."""
    runtime.stream_writer(SEARCH_PROGRESS)
    result = await expert_graph.ainvoke(build_initial_pipeline_state(query))
    answer: str = result["answer"]
    raw_sources = result.get("sources", [])

    existing_sources: list[dict[str, str]] = (
        list(runtime.state.get("retrieved_sources") or []) if runtime.state else []
    )
    seen_urls = {item["url"] for item in existing_sources if "url" in item}
    updated_sources = list(existing_sources)

    for s in raw_sources:
        s_dict = _source_to_dict(s)
        if s_dict["url"] and s_dict["url"] not in seen_urls:
            seen_urls.add(s_dict["url"])
            updated_sources.append(s_dict)

    existing_synthesis: list[str] = (
        list(runtime.state.get("expert_synthesis") or []) if runtime.state else []
    )
    updated_synthesis = [*existing_synthesis, answer]

    return Command(
        update={
            "retrieved_sources": updated_sources,
            "expert_synthesis": updated_synthesis,
            "messages": [
                ToolMessage(
                    content=f"Synthesized verified research on '{query}' from {len(raw_sources)} sources.",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": answer},
                )
            ],
        }
    )
