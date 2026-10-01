"""Shared fakes for the deep forecaster's tests; grows per unit."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from agents.deep_forecaster.state import (
    Ballot,
    Claim,
    ForecastRun,
    ForecastState,
    PassageRef,
    ResearchOutcome,
    Stance,
    Vote,
)
from models import Source

TODAY = date(2026, 9, 30)


@pytest.fixture
def events() -> list[dict[str, Any]]:
    """Progress frames the run's writer appends to."""
    return []


def runtime(events: list[dict[str, Any]]) -> SimpleNamespace:
    """Return a stand-in for the graph's `Runtime` (unit 04 adds `today`)."""
    return SimpleNamespace(
        context=ForecastRun(today=TODAY), stream_writer=events.append
    )


def sources() -> list[Source]:
    """Two sources on two different hosts, three paragraphs (lines) each."""
    return [
        Source(
            "A article",
            "https://carnegieendowment.org/a",
            "Alpha one.\nAlpha two.\nAlpha three.",
            author="Alexander Gabuev",
        ),
        Source(
            "B article",
            "https://reuters.com/b",
            "Beta one.\nBeta two.\nBeta three.",
            author="",
        ),
    ]


def claims() -> list[Claim]:
    """Two claims: Claim 1 quotes [1.1] and [2.2]; Claim 2 quotes [1.3]."""
    return [
        Claim(
            statement="Alpha happens by 2027.",
            deadline=date(2027, 12, 31),
            passages=[
                PassageRef(source=1, paragraph=1),
                PassageRef(source=2, paragraph=2),
            ],
        ),
        Claim(
            statement="Beta happens by 2028.",
            deadline=date(2028, 6, 30),
            passages=[PassageRef(source=1, paragraph=3)],
        ),
    ]


def ballot(
    stances: list["Stance"], evidence: dict[int, list[int]] | None = None
) -> Ballot:
    """One member's ballot: one vote per given stance, in claim order."""
    evidence = evidence or {}
    votes = [
        Vote(
            claim=number,
            stance=stance,
            reason=f"Reason {number}.",
            evidence=evidence.get(number, [1] if stance != "unsure" else []),
        )
        for number, stance in enumerate(stances, start=1)
    ]
    return Ballot(votes=votes)


def state(
    *,
    claims_list: list[Claim] | None = None,
    research: ResearchOutcome | None = None,
    round_1: dict[int, Ballot] | None = None,
    round_2: dict[int, Ballot] | None = None,
) -> ForecastState:
    """A `ForecastState` with two sources, two claims, and the given ballots."""
    claims_list = claims_list or claims()
    round_1 = (
        round_1
        if round_1 is not None
        else {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    )
    return ForecastState(
        question="Will it happen?",
        sources=sources(),
        research=research or ResearchOutcome(2, 0, False),
        claims=claims_list,
        ballots_round_1=round_1,
        ballots_round_2=round_2 or {},
    )
