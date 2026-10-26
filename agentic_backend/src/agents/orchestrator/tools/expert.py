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
from agents.orchestrator.state import OrchestratorState


@tool
async def run_expert(
    query: str, runtime: ToolRuntime[Any, OrchestratorState]
) -> Command[Any]:
    """Search allow-listed sources and synthesize a verified geopolitical answer."""
    runtime.stream_writer(SEARCH_PROGRESS)
    result = await expert_graph.ainvoke(build_initial_pipeline_state(query))
    answer: str = result["answer"]
    source_count = len(result.get("sources", []))

    expert_synthesis = [*(runtime.state.get("expert_synthesis") or []), answer]

    return Command(
        update={
            "expert_synthesis": expert_synthesis,
            "messages": [
                ToolMessage(
                    content=f"Synthesized verified research on '{query}' from {source_count} sources.",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": answer},
                )
            ],
        }
    )
