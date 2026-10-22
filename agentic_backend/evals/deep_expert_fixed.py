"""deep_expert_fixed eval: the deep answer from recorded sources, judged against the expert's own."""

from __future__ import annotations

import asyncio
from typing import Any

from evals.helpers.run import run
from evals.judges.deep_expert_fixed import judges

# 2x the deep agent's wall cap (`ResearchLimits.wall_seconds`, 480 s), which one
# deep run cannot exceed, leaving the rest for the expert's live `answer`. Judges
# run in a separate call with their own timeout. Retune if `wall_seconds` changes.
TIMEOUT_SECONDS = 960


async def run_deep_expert_fixed(input: dict[str, Any]) -> dict[str, Any]:
    """Write the deep answer, then the expert's baseline, both from the case's recorded pages.

    `baseline_answer` is the expert's, run live (brainstorm 2026Oct13 Q9A): a
    stored one would go stale on the first expert prompt change. The runner
    replays the pages, so Brave is never called.
    """
    from agents.deep_expert import research
    from agents.expert import build_initial_pipeline_state
    from agents.expert import graph as expert_graph

    progress: list[str] = []

    def writer(event: Any) -> None:
        if isinstance(event, dict) and event.get("type") == "progress":
            progress.append(str(event.get("label")))

    answer = await research(input["query"], writer)
    baseline = await expert_graph.ainvoke(build_initial_pipeline_state(input["query"]))
    # Searches spent and revision rounds are visible in the labels; the final
    # grader verdict is logged by `research()`.
    return {
        "answer": answer,
        "baseline_answer": baseline["answer"],
        "progress": progress,
    }


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="deep_expert_fixed",
            task=run_deep_expert_fixed,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
