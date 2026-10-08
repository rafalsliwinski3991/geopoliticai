"""e2e_deep_forecaster eval: the whole deep forecaster with live page reading.

User decision 2026-10-08 (review thread #149): one example where nothing is
recorded — Brave runs live, pages are fetched and read with trafilatura, and
This is the expensive, non-deterministic sibling of `evals/deep_forecaster.py`
(recorded sources, live council): a run costs real Brave requests and the
research lead's and scouts' live model spend, on top of the council's, and
takes up to ~2x the forecaster's wall clock.
Judges score shape and self-consistency only, never a reference answer:
- `evals/judges/e2e_deep_forecaster.py`'s `claims_checkable` and
  `prose_matches_tally` (rooms from `evals/judges/deep_forecaster.py`, views
  shared).
- The expert's two source judges need recorded sources to compare against; a
  live run has none, so they are deliberately absent here (their checks are
  the recorded evals' job).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from evals.helpers.run import run
from evals.judges.e2e_deep_forecaster import judges as e2e_judges

DATASET_PATH = Path(__file__).parent / "datasets" / "e2e_deep_forecaster.json"
# 2.5x the forecaster's wall cap (840 s): live reading and a live council.
# The graph runs without `forecast()`'s wall cap, so this timeout bounds a
# runaway example.
TIMEOUT_SECONDS = 2_100


async def run_e2e_deep_forecaster(input: dict[str, Any]) -> dict[str, Any]:
    """Run the forecaster's graph on one live scenario, nothing recorded."""
    from agents.deep_expert.graph import NO_CHECKPOINTER_CONFIG
    from agents.deep_forecaster.graph import build_graph
    from agents.deep_forecaster.state import ForecastRun
    from config import require_env
    from evals.deep_forecaster import forecast_output

    # The council's Gemini seat runs live too, and Brave is not patched away.
    require_env(
        ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "BRAVE_SEARCH_KEY")
    )
    state = await build_graph().ainvoke(
        {"question": input["query"]},
        config=NO_CHECKPOINTER_CONFIG,
        context=ForecastRun(),
    )
    return forecast_output(state)


if __name__ == "__main__":
    asyncio.run(
        run(
            eval_name="e2e_deep_forecaster",
            dataset_path=DATASET_PATH,
            task=run_e2e_deep_forecaster,
            judges=e2e_judges(),
            timeout=TIMEOUT_SECONDS,
        )
    )
