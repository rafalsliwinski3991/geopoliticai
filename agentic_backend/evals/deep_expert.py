"""Deep expert eval: `deep_answer` from recorded sources, judged against the expert's `answer`."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from evals.helpers.graph import load_sources, recorded_sources
from evals.helpers.run import run
from evals.judges.deep_expert import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "deep_expert.json"
# 2x the deep agent's wall cap (`ResearchLimits.wall_seconds`, 480 s), which one
# deep run cannot exceed, leaving the rest for the expert's live `answer`. Judges
# run in a separate call with their own timeout. Retune if `wall_seconds` changes.
TIMEOUT_SECONDS = 960


async def run_deep_expert(input: dict[str, Any]) -> dict[str, Any]:
    """Write `deep_answer` and the expert's `answer` for one query, from the same recorded sources.

    `answer` is the expert's, run live (brainstorm Q9A): a stored one would go
    stale on the first expert prompt change. Brave is never called.
    """
    from agents.deep_expert import research
    from agents.expert import build_initial_pipeline_state
    from agents.expert import graph as expert_graph

    sources = load_sources(input["sources"])
    progress: list[str] = []

    def writer(event: Any) -> None:
        if isinstance(event, dict) and event.get("type") == "progress":
            progress.append(str(event.get("label")))

    with recorded_sources(lambda: sources):
        deep_answer = await research(input["query"], writer)
        answer = (
            await expert_graph.ainvoke(build_initial_pipeline_state(input["query"]))
        )["answer"]
    # Searches spent and revision rounds are visible in the labels; the final
    # grader verdict is logged by `research()`.
    return {"deep_answer": deep_answer, "answer": answer, "progress": progress}


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="deep_expert",
            dataset_path=DATASET_PATH,
            task=run_deep_expert,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
