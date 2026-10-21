"""expert_fixed eval: the answer written from a case's recorded sources."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.run import run
from evals.judges.expert_fixed import judges


async def run_expert_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Answer one query; the runner replays the case's recorded pages, so Brave is never called."""
    from agents.expert import build_initial_pipeline_state, graph

    result = await graph.ainvoke(build_initial_pipeline_state(input["query"]))
    return {"answer": result["answer"]}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="expert_fixed",
            task=run_expert_fixed,
            judges=judges(),
        )
    )
