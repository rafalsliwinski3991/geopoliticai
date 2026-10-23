"""Specialist tool: structured report compilation."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.orchestrator.state import GeopoliticState
from agents.reporter import (
    build_initial_reporter_state,
    build_transcript,
    has_researched_material,
)
from agents.reporter import graph as reporter_graph
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE


@tool
async def run_reporter(
    topic: str, runtime: ToolRuntime[Any, GeopoliticState]
) -> Command[Any]:
    """Compile a comprehensive structured report from researched workspace material."""
    state = runtime.state or {}
    messages = state.get("messages", [])
    expert_synthesis = state.get("expert_synthesis")
    forecast_data = state.get("forecast_data")

    if not has_researched_material(messages, expert_synthesis, forecast_data):
        runtime.stream_writer({"type": "notice", "text": NO_MATERIAL_NOTICE})
        return Command(
            update={
                "report_draft": NO_MATERIAL_NOTICE,
                "messages": [
                    ToolMessage(
                        content=NO_MATERIAL_NOTICE,
                        tool_call_id=runtime.tool_call_id or "",
                        artifact={"text": NO_MATERIAL_NOTICE},
                    )
                ],
            }
        )

    transcript = build_transcript(messages)
    result = await reporter_graph.ainvoke(build_initial_reporter_state(transcript))
    report: str = result.get("report") or ""
    text = report or result.get("notice") or CANCELLED_NOTICE

    if not report:
        runtime.stream_writer({"type": "notice", "text": text})

    return Command(
        update={
            "report_draft": text,
            "messages": [
                ToolMessage(
                    content=f"Report compiled ({len(report)} chars).",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": text},
                )
            ],
        }
    )
