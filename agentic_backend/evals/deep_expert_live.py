"""deep_expert_live eval: the deep expert live, judged against the expert on the same pages."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.graph import dump_sources, record_sources, replay_sources
from evals.helpers.run import run
from evals.judges.deep_expert_live import judges
from models import Source

# 2x the deep agent's wall cap (`ResearchLimits.wall_seconds`, 480 s), which one
# deep run cannot exceed, leaving the rest for the expert's baseline. Retune if
# `wall_seconds` changes.
TIMEOUT_SECONDS = 960


async def run_deep_expert_live(input: dict[str, Any]) -> dict[str, Any]:
    """Research one query live, then let the expert answer from exactly the pages it read.

    The baseline reads the deep run's pages through `replay_sources` (brainstorm
    2026Oct21 R7.2): an expert searching on its own would read other pages, and
    depth would measure search luck. One more model call, no second search.
    """
    from agents.deep_expert import research
    from agents.expert import build_initial_pipeline_state
    from agents.expert import graph as expert_graph

    pages: list[Source] = []
    with record_sources(pages):
        answer = await research(input["query"], _drop_progress)
    with replay_sources(lambda: pages):
        baseline = await expert_graph.ainvoke(
            build_initial_pipeline_state(input["query"])
        )
    return {
        "answer": answer,
        "baseline_answer": baseline["answer"],
        "sources": dump_sources(pages),
    }


def _drop_progress(event: Any) -> None:
    """Ignore the agent's progress frames: no browser is listening."""


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="deep_expert_live",
            task=run_deep_expert_live,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
