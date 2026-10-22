"""The tally (graph node 5): the final round counted in code (Q7)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agents.deep_forecaster.council import count_votes, final_ballots
from agents.deep_forecaster.models import Ballot, Stance
from agents.deep_forecaster.state import ClaimTally, ForecastState
from tracing import start_span


async def tally(state: ForecastState) -> dict[str, Any]:
    """Count each member's latest ballot; the verdicts are code's, never a model's."""
    first, second = state["ballots_round_1"], state["ballots_round_2"]
    final = final_ballots(first, second)
    tallies = count_votes(len(state["claims"]), final)
    with start_span("council_tally") as span:
        span.set_attributes(_describe_tally(first, second, tallies))
    return {"tally": tallies, "final_ballots": final}


def _describe_tally(
    first: Mapping[int, Ballot],
    second: Mapping[int, Ballot],
    tallies: Sequence[ClaimTally],
) -> dict[str, Any]:
    """Return the `council_tally` span's attributes: the verdicts, and how much round 2 moved.

    `tally.changed_votes` counts the round-2 votes whose stance differs from
    the same member's round-1 vote: zero means Delphi's second round changed
    nothing (brainstorm 2026Sep30 F4).
    """
    changed = sum(
        1
        for member, ballot in second.items()
        if member in first
        for vote in ballot.votes
        if vote.stance != _stance_on(first[member], vote.claim)
    )
    verdicts = [counted.verdict for counted in tallies]
    return {
        "tally.claims": len(tallies),
        "tally.voting": tallies[0].voting if tallies else 0,
        "tally.accepted": verdicts.count("ACCEPTED"),
        "tally.rejected": verdicts.count("REJECTED"),
        "tally.unresolved": verdicts.count("UNRESOLVED"),
        "tally.carried_votes": len(set(first) - set(second)),
        "tally.unanimous_claims": sum(
            1
            for counted in tallies
            if counted.voting in (counted.votes_for, counted.against, counted.unsure)
        ),
        "tally.changed_votes": changed,
    }


def _stance_on(ballot: Ballot, claim: int) -> Stance | None:
    """Return `ballot`'s stance on `claim`, or None when it has no vote on it."""
    return next((vote.stance for vote in ballot.votes if vote.claim == claim), None)
