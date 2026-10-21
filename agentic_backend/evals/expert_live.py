"""expert_live eval: the expert, live on Brave and today's pages, on settled past events."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.graph import dump_sources
from evals.helpers.run import run
from evals.judges.expert_live import judges

# Three Brave batches (10 s each), page fetches (5 s each, concurrent), and the
# answer model (60 s), with room for its retries.
TIMEOUT_SECONDS = 300


async def run_expert_live(input: dict[str, Any]) -> dict[str, Any]:
    """Answer one query live; return the answer and the pages the expert read."""
    from agents.expert import build_initial_pipeline_state, graph

    result = await graph.ainvoke(build_initial_pipeline_state(input["query"]))
    return {"answer": result["answer"], "sources": dump_sources(result["sources"])}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="expert_live",
            task=run_expert_live,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
