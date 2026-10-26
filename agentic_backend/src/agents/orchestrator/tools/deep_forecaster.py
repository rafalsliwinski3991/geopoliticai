"""Specialist tool: deep forecaster Delphi prediction."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.deep_forecaster import forecast
from agents.orchestrator.state import OrchestratorState


@tool
async def run_deep_forecaster(
    question: str, runtime: ToolRuntime[Any, OrchestratorState]
) -> Command[Any]:
    """Generate a probabilistic Delphi forecast and analysis on a future event question."""
    answer = await forecast(question, runtime.store)
    runtime.stream_writer({"type": "notice", "text": answer})

    updated_forecasts = [
        *(runtime.state.get("forecast_data") or []),
        {"question": question, "summary": answer},
    ]

    return Command(
        update={
            "forecast_data": updated_forecasts,
            "messages": [
                ToolMessage(
                    content=f"Delphi forecast on '{question}' completed.",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": answer},
                )
            ],
        }
    )
