"""Reporter eval: outline, scripted gate replies, and the written report."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from evals.helpers.graph import pending_pause
from evals.helpers.run import run
from evals.judges.reporter import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "reporter.json"
TIMEOUT_SECONDS = 600


async def run_reporter(input: dict[str, Any]) -> dict[str, Any]:
    """Build a report from a transcript, feeding each scripted gate reply in order."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from agents.reporter import build_graph, build_initial_reporter_state

    graph = build_graph(checkpointer=InMemorySaver())
    config: dict[str, Any] = {"configurable": {"thread_id": f"eval-{uuid4()}"}}
    result = await graph.ainvoke(
        build_initial_reporter_state(input["transcript"]), config
    )
    for resume in input["resumes"]:
        if await pending_pause(graph, config) is None:
            raise RuntimeError(
                "A gate reply is scripted, but the reporter is not paused."
            )
        result = await graph.ainvoke(Command(resume=resume), config)
    if await pending_pause(graph, config) is not None:
        raise RuntimeError("The reporter is still paused after every scripted reply.")
    return {
        "outline": list(result["outline"]),
        "notice": result["notice"],
        "report": result["report"],
    }


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="reporter",
            dataset_path=DATASET_PATH,
            task=run_reporter,
            judges=judges(),
            # Outline (120 s) plus write (300 s) model timeouts, with room to spare.
            timeout=TIMEOUT_SECONDS,
        )
    )
