"""Specialist tool: deep expert iterative research."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.deep_expert import research
from agents.orchestrator.state import GeopoliticState


@tool
async def run_deep_expert(
    query: str, runtime: ToolRuntime[Any, GeopoliticState]
) -> Command[Any]:
    """Execute deep research and synthesis on an explicitly requested complex topic."""
    deep_answer = await research(query, runtime.stream_writer)
    runtime.stream_writer({"type": "notice", "text": deep_answer})

    parsed_citations = [
        {"title": m[0], "url": m[1]}
        for m in re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", deep_answer)
    ]

    existing_sources: list[dict[str, str]] = (
        list(runtime.state.get("retrieved_sources") or []) if runtime.state else []
    )
    seen_urls = {item["url"] for item in existing_sources if "url" in item}
    updated_sources = list(existing_sources)

    for cite in parsed_citations:
        if cite["url"] and cite["url"] not in seen_urls:
            seen_urls.add(cite["url"])
            updated_sources.append(cite)

    existing_synthesis: list[str] = (
        list(runtime.state.get("expert_synthesis") or []) if runtime.state else []
    )
    updated_synthesis = [*existing_synthesis, deep_answer]

    return Command(
        update={
            "retrieved_sources": updated_sources,
            "expert_synthesis": updated_synthesis,
            "messages": [
                ToolMessage(
                    content=f"Deep research on '{query}' synthesized.",
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": deep_answer},
                )
            ],
        }
    )
