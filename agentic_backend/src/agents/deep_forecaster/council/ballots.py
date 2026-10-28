"""The council's ballot rules: what a ballot must satisfy and how votes are counted."""

from __future__ import annotations

from collections.abc import Mapping

from agents.deep_forecaster.config import (
    LIMITS,
)
from agents.deep_forecaster.models import Ballot, Verdict
from agents.deep_forecaster.prompts import (
    ROUND_TWO_INSTRUCTIONS,
)
from agents.deep_forecaster.render import render_ballot, render_numbers
from agents.deep_forecaster.state import ClaimTally


def validate_ballot(
    ballot: Ballot, *, claims: int, quoted_by_claim: Mapping[int, frozenset[int]]
) -> str | None:
    """Return why `ballot` cannot be counted, or None when it can (F3).

    `quoted_by_claim` holds, per claim, the numbers of the sources whose
    passages that claim quotes (`evidence.quoted_sources_by_claim`): a vote on
    claim 1 may cite only what claim 1 quotes, evidence from another claim's
    sources is evidence the vote was not given, and a repeated number counts
    once (review thread, #142).

    The reason names the claim and the numbers: the member reads it in its
    re-ask, and the operator in the log and on the `council_member` span
    (brainstorm 2026Oct19 Q1).
    """
    voted = sorted(vote.claim for vote in ballot.votes)
    if voted != list(range(1, claims + 1)):
        return (
            f"it must vote exactly once on each of claims 1 to {claims}; "
            f"it voted on {render_numbers(voted) or 'none'}"
        )
    for vote in ballot.votes:
        claim = vote.claim
        reason = vote.reason.strip()
        if not reason:
            return f"claim {claim}'s reason is empty"
        if len(reason) > LIMITS.max_reason_chars:
            return (
                f"claim {claim}'s reason is {len(reason)} characters; "
                f"the limit is {LIMITS.max_reason_chars}"
            )
        if len(vote.evidence) > LIMITS.max_evidences:
            return (
                f"claim {claim} cites {len(vote.evidence)} sources; "
                f"the limit is {LIMITS.max_evidences}"
            )
        repeated = sorted({n for n in vote.evidence if vote.evidence.count(n) > 1})
        if repeated:
            return (
                f"claim {claim} cites source {render_numbers(repeated)} more than once"
            )
        own = quoted_by_claim[claim]
        stray = sorted(set(vote.evidence) - own)
        if stray:
            return (
                f"claim {claim} cites source {render_numbers(stray)}, which is not "
                f"among claim {claim}'s passages (it may cite "
                f"{render_numbers(sorted(own))})"
            )
        if vote.stance != "unsure" and not vote.evidence:
            return f"claim {claim}'s '{vote.stance}' vote cites no source"
    return None


def count_votes(claims: int, ballots: Mapping[int, Ballot]) -> list[ClaimTally]:
    """Tally the final round: 2/3 of those voting, rounded up, decides (Q7)."""
    voting = len(ballots)
    threshold = -(-2 * voting // 3)
    tallies = []
    for number in range(1, claims + 1):
        stances = [
            vote.stance
            for ballot in ballots.values()
            for vote in ballot.votes
            if vote.claim == number
        ]
        votes_for, against = stances.count("for"), stances.count("against")
        verdict: Verdict = (
            "ACCEPTED"
            if votes_for >= threshold
            else "REJECTED"
            if against >= threshold
            else "UNRESOLVED"
        )
        tallies.append(
            ClaimTally(
                claim=number,
                verdict=verdict,
                votes_for=votes_for,
                against=against,
                unsure=stances.count("unsure"),
                voting=voting,
            )
        )
    return tallies


def final_ballots(
    first: Mapping[int, Ballot], second: Mapping[int, Ballot]
) -> dict[int, Ballot]:
    """Return each round-1 voter's latest ballot: its revision, else its first vote."""
    return {member: second.get(member, ballot) for member, ballot in first.items()}


def round_one_view(member: int, ballots: Mapping[int, Ballot]) -> str:
    """Return what `member` reads in round 2: its own votes, then the others' (Q11)."""
    parts = [
        ROUND_TWO_INSTRUCTIONS,
        "",
        "Your round-1 votes:",
        render_ballot(ballots[member]),
    ]
    for other in sorted(ballots):
        if other != member:
            parts += ["", f"Member {other}:", render_ballot(ballots[other])]
    return "\n".join(parts)
