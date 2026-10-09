"""The tally (graph node 5): the final round counted in code (Q7)."""

from __future__ import annotations

from typing import Any

from agents.deep_forecaster.council import count_votes, final_ballots
from agents.deep_forecaster.state import ForecastState


async def tally(state: ForecastState) -> dict[str, Any]:
    """Count each member's latest ballot; the verdicts are code's, never a model's."""
    final = final_ballots(state["ballots_round_1"], state["ballots_round_2"])
    return {"tally": count_votes(len(state["claims"]), final)}
