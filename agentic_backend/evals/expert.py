"""Expert eval: the answer written from an example's recorded sources."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from evals.helpers.graph import load_sources, recorded_sources
from evals.helpers.run import run
from evals.judges.expert import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "expert.json"


async def run_expert(input: dict[str, Any]) -> dict[str, Any]:
    """Answer one query from its recorded sources; Brave is never called."""
    from agents.expert import build_initial_pipeline_state, graph

    sources = load_sources(input["sources"])
    with recorded_sources(lambda: sources):
        result = await graph.ainvoke(build_initial_pipeline_state(input["query"]))
    return {"answer": result["answer"]}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="expert",
            dataset_path=DATASET_PATH,
            task=run_expert,
            judges=judges(),
        )
    )
