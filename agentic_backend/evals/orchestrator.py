"""Orchestrator eval: routing and the chat path; expert, deep expert and reporter never run."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import messages_from_dict

from evals.helpers.run import run
from evals.judges.orchestrator import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "orchestrator.json"


async def run_orchestrator(input: dict[str, Any]) -> dict[str, Any]:
    """Route one conversation; answer it only when it stays on the chat path.

    Agent imports are function-local: `agents.*.graph` calls `init_tracing()`
    at import, which must happen after `run` has loaded the environment, and
    importing agents at module scope would drag the stack into unit tests.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from agents.orchestrator import build_graph, build_runtime_config

    graph = build_graph(checkpointer=InMemorySaver())
    result = await graph.ainvoke(
        {"messages": messages_from_dict(input["messages"])},
        config=build_runtime_config(thread_id=f"eval-{uuid4()}"),
        # Stops after classify on these branches: no Brave, no research, no reporter.
        interrupt_before=["expert", "deep_expert", "reporter"],
    )
    destination = result["destination"]
    return {
        "destination": destination,
        "standalone_query": result["standalone_query"],
        "answer": result["messages"][-1].text if destination == "other" else None,
    }


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="orchestrator",
            dataset_path=DATASET_PATH,
            task=run_orchestrator,
            judges=judges(),
        )
    )
