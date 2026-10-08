"""Unit tests for `evals.deep_forecaster`'s forecast shaping logic."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from agents.deep_forecaster.models import Ballot, Claim, Stance, Vote
from agents.deep_forecaster.state import ClaimTally
from evals.deep_forecaster import forecast_output


def _ballot(stances: list[str]) -> Ballot:
    return Ballot(
        votes=[
            Vote(
                claim=number,
                stance=stance,
                reason="Because of the read pages.",
                evidence=[1] if stance != "unsure" else [],
            )
            for number, stance in enumerate(cast(list[Stance], stances), start=1)
        ]
    )


def _state() -> dict[str, Any]:
    first = {member: _ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: _ballot(["for", "against"]) for member in range(1, 6)}
    claims = [
        Claim(
            statement="Claim one happens by 2027.",
            deadline=date(2027, 12, 31),
            evidence=[],
        ),
        Claim(
            statement="Claim two happens by 2028.",
            deadline=date(2028, 6, 30),
            evidence=[],
        ),
    ]
    return {
        "answer": "Overview. ## Claim 1.",
        "claims": claims,
        "ballots_round_1": first,
        "ballots_round_2": second,
        "tally": [
            ClaimTally(
                claim=1, verdict="ACCEPTED", votes_for=5, against=1, unsure=0, voting=6
            ),
            ClaimTally(
                claim=2, verdict="REJECTED", votes_for=0, against=6, unsure=0, voting=6
            ),
        ],
    }


def test_forecast_output_reports_verdicts_and_the_unanimous_share() -> None:
    # Arrange + Act
    output = forecast_output(_state())
    # Assert: claim 1 is unanimous (every counted vote says "for"), while
    # member 6 kept its round-1 "unsure" on claim 2.
    assert output["verdicts"] == ["Claim 1: ACCEPTED", "Claim 2: REJECTED"]
    assert output["unanimous_share"] == pytest.approx(0.5)
    assert output["claims"][0] == (
        "Claim 1: Claim one happens by 2027. (deadline: 2027-12-31)"
    )


def test_forecast_output_counts_a_unanimous_claim_once() -> None:
    # Arrange: everyone in round 1 is unsure; round 2 says "against" for all.
    first = {member: _ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: _ballot(["for", "against"]) for member in range(1, 8)}
    state = _state() | {"ballots_round_1": first, "ballots_round_2": second}
    # Act
    output = forecast_output(state)
    # Assert: every counted vote says the same thing on both claims.
    assert output["unanimous_share"] == pytest.approx(1.0)
