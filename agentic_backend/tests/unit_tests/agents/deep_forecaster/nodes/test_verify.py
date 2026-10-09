"""Unit tests for `agents.deep_forecaster.nodes.verify`."""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

import pytest

from agents.deep_forecaster.council import count_votes
from agents.deep_forecaster.models import (
    Analysis,
    Ballot,
    Claim,
    ClaimDiscussion,
    EvidenceRef,
    Vote,
)
from agents.deep_forecaster.state import ClaimTally, ForecastState, ResearchOutcome
from models import LLMInvocationError, Source
from unit_tests.agents.deep_forecaster.conftest import ballot, runtime, state

verify_module: Any = importlib.import_module("agents.deep_forecaster.nodes.verify")

VOTING6_TALLY = [
    ClaimTally(claim=1, verdict="ACCEPTED", votes_for=5, against=1, unsure=0, voting=6),
    ClaimTally(
        claim=2, verdict="UNRESOLVED", votes_for=0, against=0, unsure=6, voting=6
    ),
]


def analysis() -> Analysis:
    """A valid analysis: links only to sources the forecast read."""
    return Analysis(
        overview="The council leans yes. [A](https://carnegieendowment.org/a)",
        claims=[
            ClaimDiscussion(
                claim=1,
                discussion="Alpha reasons. [A](https://carnegieendowment.org/a)",
            ),
            ClaimDiscussion(
                claim=2, discussion="Beta reasons. [B](https://reuters.com/b)"
            ),
        ],
    )


def six_voters() -> dict[int, Ballot]:
    """Round-1 ballots of members 1-6; member 2 against with source 2's evidence."""
    return {
        1: ballot(["for", "unsure"]),
        2: ballot(["against", "unsure"], evidence={1: [2]}),
        3: ballot(["for", "unsure"]),
        4: ballot(["for", "unsure"]),
        5: ballot(["for", "unsure"]),
        6: ballot(["for", "unsure"]),
    }


def checked(forecast_state: Any, analysis_: Analysis | None = None) -> str:
    """Run `checked_answer` on `forecast_state`, with its ballots and tally."""
    revised = set(forecast_state["ballots_round_2"])
    answer: str = verify_module.checked_answer(
        analysis_ or analysis(),
        forecast_state["claims"],
        forecast_state["tally"],
        verify_module.final_ballots(
            forecast_state["ballots_round_1"], forecast_state["ballots_round_2"]
        ),
        revised,
        forecast_state["sources"],
        forecast_state["research"],
    )
    return answer


@pytest.mark.anyio
async def test_the_answer_renders_the_tally_and_every_vote(
    events: list[dict[str, Any]],
) -> None:
    # Arrange
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    out = await verify_module.verify(forecast_state, runtime(events))
    answer = out["answer"]
    # Act
    for part in (
        "The council leans yes.",
        "## Claim 1: Alpha happens by 2027.",
        "Council verdict: **ACCEPTED**",
        "## How the council voted",
        "Members voting: 6 of 7 (1 unavailable).",
        "Evidence: 2 sources read from 2 sites. The council voted on 3 passages "
        "quoted from 2 of them.",
        "### Claim 1: ACCEPTED",
        "5 of 6 voted for, 1 against, 0 unsure.",
        "- Member 2: against — Reason 1. ([Source 2](https://reuters.com/b))",
    ):
        assert part in answer, part
    # Assert
    assert "Round 2:" not in answer


@pytest.mark.anyio
async def test_seven_voting_shows_no_unavailable_count(
    events: list[dict[str, Any]],
) -> None:
    # Arrange
    # Arrange
    forecast_state: Any = state(
        round_2={member: ballot(["for", "unsure"]) for member in range(1, 8)}
    )
    forecast_state["tally"] = count_votes(
        2,
        verify_module.final_ballots(
            forecast_state["ballots_round_1"], forecast_state["ballots_round_2"]
        ),
    )
    forecast_state["analysis"] = analysis()
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert "Members voting: 7 of 7." in answer
    assert "unavailable" not in answer


@pytest.mark.anyio
async def test_a_reason_is_flattened_to_one_line(events: list[dict[str, Any]]) -> None:
    # Arrange
    # Arrange
    one = Ballot(
        votes=[
            Vote(
                claim=1,
                stance="for",
                reason="Line one.\nLine two, see https://spam.example/x for more.",
                evidence=[1],
            ),
            Vote(claim=2, stance="unsure", reason="Reason 2.", evidence=[]),
        ]
    )
    first = {1: one, **{member: ballot(["for", "unsure"]) for member in range(2, 7)}}
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "- Member 1: for — Line one. Line two, see (link removed) for more." in answer
    )
    assert "https://spam.example" not in answer


@pytest.mark.anyio
async def test_a_carried_vote_is_marked(events: list[dict[str, Any]]) -> None:
    # Arrange
    # Arrange
    first = six_voters()
    second = {member: one for member, one in first.items() if member != 4}
    forecast_state: Any = state(round_1=first, round_2=second)
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "Round 2: 1 of 6 kept their round-1 vote because they did not answer." in answer
    )
    assert "- Member 4 (round-1 vote): for — Reason 1." in answer


@pytest.mark.parametrize(
    ("sources_", "claims_", "research_", "expected"),
    [
        pytest.param(
            [Source("T", "https://carnegieendowment.org/a", "Alpha.\nBeta.\nGamma.")],
            [
                Claim(
                    statement="S.",
                    deadline=date(2027, 12, 31),
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ],
            ResearchOutcome(1, 0, False),
            "Evidence: 1 source read from 1 site. The council voted on 1 passage "
            "quoted from 1 of them.",
            id="one source, one passage",
        ),
        pytest.param(
            [
                Source("A", "https://www.carnegieendowment.org/a", "One.\nTwo."),
                Source("B", "https://carnegieendowment.org/b", "Three."),
                Source("V", "https://m.youtube.com/watch?v=x", "Four.\nFive."),
            ],
            [
                Claim(
                    statement="S.",
                    deadline=date(2027, 12, 31),
                    evidence=[
                        EvidenceRef(source=1, paragraph=1),
                        EvidenceRef(source=3, paragraph=1),
                        EvidenceRef(source=1, paragraph=2),
                        EvidenceRef(source=3, paragraph=2),
                    ],
                )
            ],
            ResearchOutcome(3, 0, False),
            "Evidence: 3 sources read from 2 sites, 1 of them Gemini's notes on a "
            "video. The council voted on 4 passages quoted from 2 of them.",
            id="three sources, two sites, one video",
        ),
        pytest.param(
            [Source("T", "https://carnegieendowment.org/a", "Alpha.")],
            [
                Claim(
                    statement="S.",
                    deadline=date(2027, 12, 31),
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ],
            ResearchOutcome(11, 3, True),
            "Evidence: 1 source read from 1 site. The council voted on 1 passage "
            "quoted from 1 of them. Research stopped at its time limit. "
            "3 of 11 searches failed.",
            id="time limit and failed searches",
        ),
        pytest.param(
            [Source("T", "https://forecasters.example/a", "Alpha.")],
            [
                Claim(
                    statement="S.",
                    deadline=date(2027, 12, 31),
                    evidence=[EvidenceRef(source=1, paragraph=1)],
                )
            ],
            ResearchOutcome(1, 0, False),
            "Evidence: 1 source read from 1 site.",
            id="a recorded eval URL counts as its host",
        ),
    ],
)
def test_the_evidence_line_reports_the_counts(
    sources_: list[Source],
    claims_: list[Claim],
    research_: ResearchOutcome,
    expected: str,
) -> None:
    # Arrange
    # Act
    line = verify_module.evidence_line(sources_, research_, claims_)
    # Assert
    assert line.startswith(expected)


def test_a_link_differing_only_in_form_is_accepted() -> None:
    # Arrange
    # Arrange
    sources_ = [Source("X", "https://carnegieendowment.org/x", "One.")]
    claim = Claim(
        statement="S.",
        deadline=date(2027, 12, 31),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    analysis_ = Analysis(
        overview=(
            "Read [A](https://WWW.Carnegieendowment.org/x/) and "
            "[B](https://carnegieendowment.org/x#s2)."
        ),
        claims=[
            ClaimDiscussion(
                claim=1, discussion="Also https://carnegieendowment.org/x. Done."
            )
        ],
    )
    # Act
    answer = checked(_state_for(sources_, [claim], {1: ballot(["for"])}), analysis_)
    # Assert
    assert "Council verdict: **ACCEPTED**" in answer


def test_an_http_citation_does_not_valid_against_an_https_source() -> None:
    # Arrange
    sources_ = [Source("X", "https://carnegieendowment.org/x", "One.")]
    claim = Claim(
        statement="S.",
        deadline=date(2027, 12, 31),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    analysis_ = Analysis(
        overview="Read [A](http://carnegieendowment.org/x).",
        claims=[ClaimDiscussion(claim=1, discussion="Done.")],
    )
    # Act
    with pytest.raises(LLMInvocationError, match="never read"):
        # Arrange
        checked(_state_for(sources_, [claim], {1: ballot(["for"])}), analysis_)
    # Assert: the raise is the assertion.


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/x",
        "<https://evil.example/y>",
        "[1]: https://evil.example/ref",
        "www.evil.example/z",
    ],
)
def test_every_clickable_link_form_is_checked(link: str) -> None:
    # Arrange
    sources_ = [Source("X", "https://carnegieendowment.org/x", "One.")]
    claim = Claim(
        statement="S.",
        deadline=date(2027, 12, 31),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    # Arrange
    analysis_ = Analysis(
        overview=f"Read [A](https://carnegieendowment.org/x) and {link}.",
        claims=[ClaimDiscussion(claim=1, discussion="Discussion.")],
    )
    # Act
    with pytest.raises(
        LLMInvocationError, match="links to a page the forecast never read"
    ):
        checked(_state_for(sources_, [claim], {1: ballot(["for"])}), analysis_)
    # Assert: the raise is the assertion.


@pytest.mark.parametrize("link", ["[x](//evil.example)", "[x](ftp://evil.example)"])
def test_a_non_clickable_link_form_is_not_checked(link: str) -> None:
    # Arrange
    # Arrange
    sources_ = [Source("X", "https://carnegieendowment.org/x", "One.")]
    claim = Claim(
        statement="S.",
        deadline=date(2027, 12, 31),
        evidence=[EvidenceRef(source=1, paragraph=1)],
    )
    analysis_ = Analysis(
        overview=f"Read [A](https://carnegieendowment.org/x) and {link}.",
        claims=[ClaimDiscussion(claim=1, discussion="Discussion.")],
    )
    # Act
    answer = checked(_state_for(sources_, [claim], {1: ballot(["for"])}), analysis_)
    # Assert
    assert "Council verdict: **ACCEPTED**" in answer


@pytest.mark.anyio
async def test_an_all_carried_round_two_is_disclosed(
    events: list[dict[str, Any]],
) -> None:
    # Arrange
    # Act
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2={})
    forecast_state["tally"] = count_votes(2, first)
    forecast_state["analysis"] = analysis()
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "Round 2: 6 of 6 kept their round-1 vote because they did not answer." in answer
    )
    for member in range(1, 7):
        assert f"- Member {member} (round-1 vote):" in answer


@pytest.mark.parametrize(
    "sections",
    [
        pytest.param([1], id="a missing claim section"),
        pytest.param([1, 1], id="a duplicate claim section"),
    ],
)
def test_a_broken_claim_section_list_raises(sections: list[int]) -> None:
    # Arrange
    analysis_ = Analysis(
        overview="Overview. [A](https://carnegieendowment.org/a)",
        claims=[
            ClaimDiscussion(
                claim=number, discussion="Discussion. [B](https://reuters.com/b)"
            )
            for number in sections
        ],
    )
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    with pytest.raises(
        LLMInvocationError, match="did not discuss every claim exactly once"
    ):
        # Act
        checked(forecast_state, analysis_)
    # Assert: the raise is the assertion.


def test_an_empty_overview_raises() -> None:
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview="   ",
        claims=[
            ClaimDiscussion(
                claim=1, discussion="Discussion. [B](https://reuters.com/b)"
            ),
            ClaimDiscussion(
                claim=2, discussion="More. [A](https://carnegieendowment.org/a)"
            ),
        ],
    )
    with pytest.raises(LLMInvocationError, match="left a section empty"):
        # Arrange
        # Act
        checked(forecast_state, analysis_)
    # Assert: the raise is the assertion.


def test_an_analysis_with_no_link_at_all_raises() -> None:
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview="Overview without links.",
        claims=[
            ClaimDiscussion(claim=1, discussion="D."),
            ClaimDiscussion(claim=2, discussion="E."),
        ],
    )
    with pytest.raises(LLMInvocationError, match="cited none of the sources"):
        # Arrange
        # Act
        checked(forecast_state, analysis_)
    # Assert: the raise is the assertion.


def test_a_link_to_an_unread_url_raises() -> None:
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview="Overview. [X](https://unread.example/x)",
        claims=[
            ClaimDiscussion(
                claim=1, discussion="D. [A](https://carnegieendowment.org/a)"
            ),
            ClaimDiscussion(claim=2, discussion="E. [B](https://reuters.com/b)"),
        ],
    )
    with pytest.raises(
        LLMInvocationError, match="links to a page the forecast never read"
    ):
        # Act
        checked(forecast_state, analysis_)
    # Assert: the raise is the assertion.


def _state_for(
    sources_: list[Source], claims_: list[Claim], round_1: dict[int, Ballot]
) -> ForecastState:
    """A state for `checked_answer`'s direct calls: one claim's tally, all revised."""
    tally = [
        ClaimTally(
            claim=1, verdict="ACCEPTED", votes_for=1, against=0, unsure=0, voting=1
        )
    ]
    return ForecastState(
        question="Will it happen?",
        sources=sources_,
        research=ResearchOutcome(1, 0, False),
        claims=claims_,
        ballots_round_1=round_1,
        ballots_round_2=dict(round_1),
        tally=tally,
    )
