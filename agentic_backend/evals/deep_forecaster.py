"""Deep forecaster eval: one whole forecast per example, from recorded sources.

The council's members are called live, all seven seats on OpenRouter: 14
council calls per example on the OpenRouter key's credits, about $0.15 per
forecast by the plan's estimate at the prices listed on 2026-10-14. The 3 model judges
spend the OpenRouter account's shared free budget (F8). Brave and Gemini's video
reading are never called: every search returns the recorded set, and no
recorded source is a video. The whole graph is invoked, not `forecast()`, so
the judges can read the claims and the tally as well as the answer.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from evals.helpers.graph import load_sources, recorded_sources
from evals.helpers.run import run
from evals.judges.deep_forecaster import judges

DATASET_PATH = Path(__file__).parent / "datasets" / "deep_forecaster.json"
# 2x the forecaster's wall cap (`ForecastLimits.wall_seconds`, 840 s). The
# graph is invoked without `forecast()`'s wall cap, so this timeout is what
# bounds a runaway example. Judges run in a separate call with their own timeout.
TIMEOUT_SECONDS = 1_680


def forecast_output(state: dict[str, Any]) -> dict[str, Any]:
    """Return what the judges read, and the share of unanimous claims (F4)."""
    # Imported here, as every eval script imports agents (`evals/deep_expert.py`).
    from agents.deep_forecaster.council import final_ballots

    claims = state["claims"]
    # The ballots the verdicts counted, carried round-1 votes included.
    ballots = final_ballots(state["ballots_round_1"], state["ballots_round_2"]).values()
    unanimous = sum(
        1
        for number in range(1, len(claims) + 1)
        if len({v.stance for b in ballots for v in b.votes if v.claim == number}) == 1
    )
    share = unanimous / len(claims)
    # F4: revisit the council's instructions if most claims come back unanimous.
    print(f"unanimous share: {share:.2f}")
    return {
        "answer": state["answer"],
        "claims": [
            f"Claim {n}: {c.statement} (deadline: {c.deadline.isoformat()})"
            for n, c in enumerate(claims, start=1)
        ],
        "verdicts": [f"Claim {t.claim}: {t.verdict}" for t in state["tally"]],
        "unanimous_share": share,
    }


async def run_deep_forecaster(input: dict[str, Any]) -> dict[str, Any]:
    """Run the forecaster's graph on one example's recorded sources."""
    from agents.deep_expert.graph import NO_CHECKPOINTER_CONFIG
    from agents.deep_forecaster.graph import build_graph
    from agents.deep_forecaster.state import ForecastRun

    sources = load_sources(input["sources"])
    with recorded_sources(lambda: sources):
        state = await build_graph().ainvoke(
            {"question": input["query"]},
            config=NO_CHECKPOINTER_CONFIG,
            # The example's as-of date keeps the claims' deadlines in the
            # example's future as the eval ages (review thread, #149).
            context=ForecastRun(today=date.fromisoformat(input["as_of"])),
        )
    return forecast_output(state)


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="deep_forecaster",
            dataset_path=DATASET_PATH,
            task=run_deep_forecaster,
            judges=judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
