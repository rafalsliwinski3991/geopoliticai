"""orchestrator_fixed eval: the orchestrator routes and rewrites recorded conversations."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.graph import load_messages
from evals.helpers.run import run
from evals.judges.orchestrator_fixed import judges


async def run_orchestrator_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the orchestrator's routing turn: tool selection and standalone rewrite."""
    from agents.orchestrator.nodes.supervisor import supervisor

    result = await supervisor(
        {"messages": load_messages(input["messages"])}, _drop_progress
    )
    destination = result.get("destination", "other")
    standalone_query = ""
    search_query = ""
    messages = result.get("messages", [])
    if messages and hasattr(messages[0], "tool_calls") and messages[0].tool_calls:
        tc = messages[0].tool_calls[0]
        args = tc.get("args", {})
        standalone_query = (
            args.get("query") or args.get("question") or args.get("topic") or ""
        )
        search_query = args.get("search_query") or ""

    return {
        "destination": destination,
        "standalone_query": standalone_query,
        "search_query": search_query,
    }


def _drop_progress(event: Any) -> None:
    """Ignore progress and notice events during offline eval."""


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="orchestrator_fixed",
            task=run_orchestrator_fixed,
            judges=judges(),
        )
    )
