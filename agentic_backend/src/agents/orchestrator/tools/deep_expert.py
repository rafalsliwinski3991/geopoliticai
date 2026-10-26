"""Specialist tool: deep expert iterative research."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.deep_expert import research
from agents.orchestrator.state import OrchestratorState


@tool
async def run_deep_expert(
    query: str, runtime: ToolRuntime[Any, OrchestratorState]
) -> Command[Any]:
    """Execute deep research and synthesis on an explicitly requested complex topic."""
    deep_answer = await research(query, runtime.stream_writer)
    runtime.stream_writer({"type": "notice", "text": deep_answer})

    expert_synthesis = [*(runtime.state.get("expert_synthesis") or []), deep_answer]

    return Command(
        update={
            "expert_synthesis": expert_synthesis,
            "messages": [
                ToolMessage(
                    content=f"Deep research on '{query}' synthesized.",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": deep_answer},
                )
            ],
        }
    )
