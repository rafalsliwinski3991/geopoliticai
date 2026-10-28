"""Specialist tool: structured report compilation."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.orchestrator.state import OrchestratorState
from agents.reporter import (
    build_transcript,
    has_researched_material,
    report,
)
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE
from shared.tracing import start_span


@tool
async def run_reporter(
    topic: str, runtime: ToolRuntime[Any, OrchestratorState]
) -> Command[Any]:
    """Compile a comprehensive structured report from researched workspace material."""
    messages = runtime.state["messages"]

    with start_span("run_reporter") as span:
        if not has_researched_material(
            messages,
            runtime.state.get("expert_synthesis"),
            runtime.state.get("forecast_data"),
        ):
            span.set_attribute("report.outcome", "no_material")
            runtime.stream_writer({"type": "notice", "text": NO_MATERIAL_NOTICE})
            return Command(
                update={
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
        result = await report(transcript)
        report_text: str = result.get("report") or ""
        text = report_text or result.get("notice") or CANCELLED_NOTICE

        if report_text:
            span.set_attribute("report.outcome", "written")
            span.set_attribute("report.chars", len(report_text))
        else:
            span.set_attribute("report.outcome", "not_written")
            runtime.stream_writer({"type": "notice", "text": text})

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"Report compiled ({len(report_text)} chars).",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": text},
                )
            ],
        }
    )
