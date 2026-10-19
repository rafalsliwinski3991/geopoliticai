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
from agents.deep_forecaster.state import ClaimTally, ResearchOutcome
from models import LLMInvocationError, Source
from unit_tests.agents.deep_forecaster.conftest import ballot, runtime, sources, state

verify_module: Any = importlib.import_module("agents.deep_forecaster.nodes.verify")

VOTING6_TALLY = [
    ClaimTally(claim=1, verdict="ACCEPTED", votes_for=5, against=1, unsure=0, voting=6),
    ClaimTally(
        claim=2, verdict="UNRESOLVED", votes_for=0, against=0, unsure=6, voting=6
    ),
]


def analysis() -> Analysis:
    """A valid analysis: every section cites the sources read, by number."""
    return Analysis(
        overview="The council leans yes. [A](source:1)",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)"),
            ClaimDiscussion(claim=2, discussion="Beta reasons. [B](source:2)"),
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
    # The citation became the URL the forecast read; no `source:` leaks through.
    assert "(https://carnegieendowment.org/a)" in answer
    assert "source:" not in answer


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


BAD_SOURCE_NUMBERS = [
    pytest.param("(source:0)", id="source zero"),
    pytest.param("(source:3)", id="one past the last source"),
    pytest.param("(source:1.2)", id="a paragraph number 1.2"),
    pytest.param("(source:x)", id="not a number"),
    pytest.param("(source:²)", id="a superscript digit ²"),
    pytest.param(f"(source:{'9' * 5000})", id="a 5000-digit run"),
]


@pytest.mark.parametrize("citation", BAD_SOURCE_NUMBERS)
def test_an_out_of_range_source_number_raises(citation: str) -> None:
    """A number naming no source the forecast read is a 502, never a crash.

    `int("²")` and a 5000-digit run would raise `ValueError` if the digit rule
    were not applied first, so the reader sees the 502 message instead.
    """
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. [A]{citation}",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons."),
            ClaimDiscussion(claim=2, discussion="Beta reasons."),
        ],
    )
    # Act + Assert
    with pytest.raises(
        LLMInvocationError, match="cites 1 source number outside 1 to 2"
    ):
        checked(forecast_state, analysis_)


UNLINKABLE_CITATIONS = [
    pytest.param('[B](source:2 "t")', id="a titled link"),
    pytest.param("<source:2>", id="angle brackets"),
    pytest.param("[B](source: 2)", id="a space after the colon"),
    pytest.param("(source:2)", id="a bare (source:2)"),
]


@pytest.mark.parametrize("broken", UNLINKABLE_CITATIONS)
def test_an_unlinkable_citation_raises(broken: str) -> None:
    """A citation the answer cannot link would ship as dead text, so it is a 502.

    One valid citation beside it must not rescue the broken one: the reader
    would see the dead text either way.
    """
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. [A](source:1) and {broken}.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons."),
            ClaimDiscussion(claim=2, discussion="Beta reasons."),
        ],
    )
    # Act + Assert
    with pytest.raises(LLMInvocationError, match="a citation the answer cannot link"):
        checked(forecast_state, analysis_)


PROSE_THAT_NAMES_A_NUMBER = [
    pytest.param("resource: 3 pilots", id="a word ending in source"),
    pytest.param("(Source: 2024 yearbook)", id="a prose source line with a year"),
]


@pytest.mark.parametrize("prose", PROSE_THAT_NAMES_A_NUMBER)
def test_ordinary_prose_is_not_a_citation(prose: str) -> None:
    """`SOURCE_MENTION` matches citation shapes only: prose whose word ends in
    "source", or a source line whose number is a year, is neither a citation
    nor a reason to fail the writer."""

    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. [A](source:1). See {prose}.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons."),
            ClaimDiscussion(claim=2, discussion="Beta reasons."),
        ],
    )

    # Act
    answer = checked(forecast_state, analysis_)

    # Assert
    assert prose in answer


@pytest.mark.parametrize(
    "citation",
    [
        pytest.param("[B](source:2)", id="lowercase source"),
        pytest.param("[B](SOURCE:2)", id="uppercase SOURCE"),
    ],
)
def test_a_citation_links_regardless_of_its_case(citation: str) -> None:
    """`SOURCE_LINK` keeps its `re.IGNORECASE`: `[B](SOURCE:2)` is linked to
    source 2's URL, not shipped as dead text."""

    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. {citation}",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)"),
            ClaimDiscussion(claim=2, discussion="Beta reasons. [A](source:1)"),
        ],
    )

    # Act
    answer = checked(forecast_state, analysis_)

    # Assert
    assert "The council leans yes. [B](https://reuters.com/b)" in answer


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://evil.example/x", id="a bare url"),
        pytest.param("<https://evil.example/y>", id="an autolink"),
        pytest.param("[1]: https://evil.example/ref", id="a reference definition"),
        pytest.param("www.evil.example/z", id="a www autolink"),
    ],
)
def test_a_raw_url_raises(url: str) -> None:
    """Any URL the writer still writes is a 502: the URLs come from the source list."""
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. [A](source:1) and {url}.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons."),
            ClaimDiscussion(claim=2, discussion="Beta reasons."),
        ],
    )
    # Act + Assert
    with pytest.raises(LLMInvocationError, match="wrote a URL"):
        checked(forecast_state, analysis_)


@pytest.mark.parametrize("link", ["[x](//evil.example)", "[x](ftp://evil.example)"])
def test_a_non_clickable_link_form_is_not_checked(link: str) -> None:
    """A link the chat UI cannot click stays unchecked: it renders as plain text."""
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        overview=f"The council leans yes. [A](source:1) and {link}.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha reasons."),
            ClaimDiscussion(claim=2, discussion="Beta reasons."),
        ],
    )
    # Act
    answer = checked(forecast_state, analysis_)
    # Assert
    assert "Council verdict: **ACCEPTED**" in answer
    assert "[A](https://carnegieendowment.org/a)" in answer


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
    # Citations by number: a URL in the prose is itself a defect, so this
    # test must not hand `find_defect` one (final review).
    analysis_ = Analysis(
        overview="Overview. [A](source:1)",
        claims=[
            ClaimDiscussion(claim=number, discussion="Discussion. [B](source:2)")
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
            ClaimDiscussion(claim=1, discussion="Discussion. [B](source:2)"),
            ClaimDiscussion(claim=2, discussion="More. [A](source:1)"),
        ],
    )
    with pytest.raises(LLMInvocationError, match="left a section empty"):
        # Arrange
        # Act
        checked(forecast_state, analysis_)
    # Assert: the raise is the assertion.


def test_an_analysis_with_no_citation_raises() -> None:
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


# Unit 05: the plan's six named broken analyses (plan §5), each a passing
# analysis with exactly one defect a rewrite can fix. Every one carries the
# marker `INJECTED-7f3a` in its prose, and inside its defective link or
# citation where it has one, so a defect that echoed the writer's own text
# would leak the marker.
MARKER = "INJECTED-7f3a"
MARKER_URL = f"https://carnegieendowment.org/{MARKER}"

MISSING_CLAIM = Analysis(
    overview=f"The council leans yes. [A](source:1) — {MARKER} saw it.",
    claims=[ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)")],
)
EMPTY_SECTION = Analysis(
    overview="The council leans yes. [A](source:1)",
    claims=[
        ClaimDiscussion(claim=1, discussion=""),
        ClaimDiscussion(
            claim=2, discussion=f"Beta reasons. [B](source:2) — {MARKER} saw it."
        ),
    ],
)
RAW_URL = Analysis(
    overview=f"The council leans yes. [A](source:1). See [more]({MARKER_URL}).",
    claims=[
        ClaimDiscussion(
            claim=1, discussion=f"Alpha reasons. [A](source:1) — {MARKER} saw it."
        ),
        ClaimDiscussion(claim=2, discussion="Beta reasons. [B](source:2)"),
    ],
)
UNLINKABLE_CITATION = Analysis(
    overview=f'The council leans yes. See [a {MARKER} note](source:1 "t").',
    claims=[
        ClaimDiscussion(claim=1, discussion=f"Alpha reasons. {MARKER} saw it."),
        ClaimDiscussion(claim=2, discussion="Beta reasons."),
    ],
)
NO_CITATION = Analysis(
    overview=f"The council leans yes. {MARKER} agrees.",
    claims=[
        ClaimDiscussion(claim=1, discussion="Alpha reasons."),
        ClaimDiscussion(claim=2, discussion="Beta reasons."),
    ],
)
UNREAD_SOURCE = Analysis(
    overview=f"The council leans yes. [{MARKER}](source:9)",
    claims=[
        ClaimDiscussion(claim=1, discussion="Alpha reasons. [A](source:1)"),
        ClaimDiscussion(claim=2, discussion="Beta reasons. [B](source:2)"),
    ],
)

# The exact defect `find_defect` must return for each named analysis, written
# by hand from the rules, never computed.
MISSING_CLAIM_DEFECT = (
    "The analysis did not discuss every claim exactly once: it needs one "
    "section for each of claims 1 and 2 and wrote sections for 1."
)
EMPTY_SECTION_DEFECT = "The analysis left a section empty: claim 1."
RAW_URL_DEFECT = (
    "The analysis wrote a URL; it must cite sources only as [anchor](source:N)."
)
UNLINKABLE_CITATION_DEFECT = (
    "The analysis wrote a citation the answer cannot link; write each one "
    "exactly as [anchor](source:N)."
)
NO_CITATION_DEFECT = "The analysis cited none of the sources it read."
UNREAD_SOURCE_DEFECT = (
    "The analysis cites 1 source number outside 1 to 2, the sources the "
    "forecast read; cite whole source numbers such as (source:3)."
)

DEFECTS = [
    pytest.param(MISSING_CLAIM, MISSING_CLAIM_DEFECT, id="a missing claim"),
    pytest.param(EMPTY_SECTION, EMPTY_SECTION_DEFECT, id="an empty section"),
    pytest.param(RAW_URL, RAW_URL_DEFECT, id="a raw url"),
    pytest.param(
        UNLINKABLE_CITATION, UNLINKABLE_CITATION_DEFECT, id="an unlinkable citation"
    ),
    pytest.param(NO_CITATION, NO_CITATION_DEFECT, id="no citation"),
    pytest.param(UNREAD_SOURCE, UNREAD_SOURCE_DEFECT, id="an unread source"),
]

BROKEN_ANALYSES = [
    pytest.param(MISSING_CLAIM, id="a missing claim"),
    pytest.param(EMPTY_SECTION, id="an empty section"),
    pytest.param(RAW_URL, id="a raw url"),
    pytest.param(UNLINKABLE_CITATION, id="an unlinkable citation"),
    pytest.param(NO_CITATION, id="no citation"),
    pytest.param(UNREAD_SOURCE, id="an unread source"),
]


@pytest.mark.parametrize(("broken_analysis", "expected_defect"), DEFECTS)
def test_find_defect_names_the_defect(
    broken_analysis: Analysis, expected_defect: str
) -> None:
    """Each defect text names the problem, so the writer's one rewrite can fix it."""
    # Arrange
    # Act
    defect = verify_module.find_defect(broken_analysis, VOTING6_TALLY, sources())
    # Assert
    assert defect == expected_defect


@pytest.mark.parametrize("broken_analysis", BROKEN_ANALYSES)
def test_a_defect_never_echoes_the_writers_text(broken_analysis: Analysis) -> None:
    """The defect is code's text: it must never quote model-written output.

    Every prose excerpt, URL, and citation in the model's analysis carries the
    marker `INJECTED-7f3a`; echoing the text would ship it back to the writer
    and, through it, potentially to a reader.
    """
    # Arrange
    # Act
    defect = verify_module.find_defect(broken_analysis, VOTING6_TALLY, sources())
    # Assert
    assert MARKER not in defect


@pytest.mark.anyio
async def test_a_first_defect_returns_feedback(events: list[dict[str, Any]]) -> None:
    """On the analysis's first defect, verify sends it back once, named."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = MISSING_CLAIM
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    assert out == {"feedback": MISSING_CLAIM_DEFECT}
    assert "answer" not in out


@pytest.mark.anyio
async def test_a_second_defect_raises(events: list[dict[str, Any]]) -> None:
    """With the one rewrite spent, a defect is a hard 502 naming the defect."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = MISSING_CLAIM
    forecast_state["feedback"] = MISSING_CLAIM_DEFECT
    # Act + Assert
    with pytest.raises(LLMInvocationError) as raised:
        await verify_module.verify(forecast_state, runtime(events))
    assert raised.value.status == 502
    assert str(raised.value) == MISSING_CLAIM_DEFECT
