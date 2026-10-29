"""Unit tests for `agents.deep_forecaster.nodes.verify`."""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

import pytest

from agents.deep_forecaster.council.ballots import count_votes, final_ballots
from agents.deep_forecaster.models import (
    Analysis,
    Ballot,
    Claim,
    ClaimDiscussion,
    EvidenceRef,
    Vote,
)
from agents.deep_forecaster.state import ClaimTally, ResearchOutcome
from models import Source
from shared.errors import LLMInvocationError
from unit_tests.agents.deep_forecaster.conftest import (
    DEFECTS,
    MARKER,
    MISSING_CLAIM,
    MISSING_CLAIM_DEFECT,
    ballot,
    runtime,
    sources,
    state,
)

verify_module: Any = importlib.import_module("agents.deep_forecaster.nodes.verify")

VOTING6_TALLY = [
    ClaimTally(claim=1, verdict="ACCEPTED", votes_for=5, against=1, unsure=0, voting=6),
    ClaimTally(
        claim=2, verdict="UNRESOLVED", votes_for=0, against=0, unsure=6, voting=6
    ),
]

OUT_OF_RANGE_DEFECT = (
    "The analysis cites 1 source number outside 1 to 2, the sources the forecast "
    "read; cite whole source numbers such as (source:3)."
)
UNLINKABLE_DEFECT = (
    "The analysis wrote a citation the answer cannot link; write each one "
    "exactly as [anchor](source:N)."
)
RAW_URL_DEFECT = (
    "The analysis wrote a URL; it must cite sources only as [anchor](source:N)."
)
DUPLICATE_SECTION_DEFECT = (
    "The analysis did not discuss every claim exactly once: it needs one section "
    "for each of claims 1 and 2 and wrote sections for 1 and 1."
)
EMPTY_OVERVIEW_DEFECT = "The analysis left a section empty: the overview."
NO_CITATION_DEFECT = "The analysis cited none of the sources it read."
PLAIN_SECTIONS = [
    ClaimDiscussion(claim=1, discussion="Alpha reasons."),
    ClaimDiscussion(claim=2, discussion="Beta reasons."),
]

# Each analysis breaks one check of `find_defect`; verify sends it back once with
# that check's message, and a second defect is a hard error. Each case keeps its
# own citation, so the message names the defect it has.
CHECKED_DEFECTS = [
    # Out of range: a number naming no source read is a 502, never a crash.
    # `int("²")` and a 5000-digit run would raise `ValueError` without the digit rule.
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:0)",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="source zero",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:3)",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="one past the last source",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1.2)",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="a paragraph number 1.2",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:x)",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="not a number",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:²)",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="a superscript digit ²",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:" + "9" * 5000 + ")",
            claims=PLAIN_SECTIONS,
        ),
        OUT_OF_RANGE_DEFECT,
        id="a 5000-digit run",
    ),
    # Unlinkable: one valid citation beside a broken one must not rescue it.
    pytest.param(
        Analysis(
            language="en",
            overview='The council leans yes. [A](source:1) and [B](source:2 "t").',
            claims=PLAIN_SECTIONS,
        ),
        UNLINKABLE_DEFECT,
        id="a titled link",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and <source:2>.",
            claims=PLAIN_SECTIONS,
        ),
        UNLINKABLE_DEFECT,
        id="angle brackets",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and [B](source: 2).",
            claims=PLAIN_SECTIONS,
        ),
        UNLINKABLE_DEFECT,
        id="a space after the colon",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and (source:2).",
            claims=PLAIN_SECTIONS,
        ),
        UNLINKABLE_DEFECT,
        id="a bare (source:2)",
    ),
    # Raw URL: any URL the writer still writes is a defect; the URLs come from the list.
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and https://evil.example/x.",
            claims=PLAIN_SECTIONS,
        ),
        RAW_URL_DEFECT,
        id="a bare url",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and <https://evil.example/y>.",
            claims=PLAIN_SECTIONS,
        ),
        RAW_URL_DEFECT,
        id="an autolink",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and [1]: https://evil.example/ref.",
            claims=PLAIN_SECTIONS,
        ),
        RAW_URL_DEFECT,
        id="a reference definition",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="The council leans yes. [A](source:1) and www.evil.example/z.",
            claims=PLAIN_SECTIONS,
        ),
        RAW_URL_DEFECT,
        id="a www autolink",
    ),
    # Claim sections: one section for each claim, no more and no fewer.
    pytest.param(
        Analysis(
            language="en",
            overview="Overview. [A](source:1)",
            claims=[ClaimDiscussion(claim=1, discussion="Discussion. [B](source:2)")],
        ),
        MISSING_CLAIM_DEFECT,
        id="a missing claim section",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="Overview. [A](source:1)",
            claims=[
                ClaimDiscussion(claim=1, discussion="Discussion. [B](source:2)"),
                ClaimDiscussion(claim=1, discussion="Discussion. [B](source:2)"),
            ],
        ),
        DUPLICATE_SECTION_DEFECT,
        id="a duplicate claim section",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="   ",
            claims=[
                ClaimDiscussion(claim=1, discussion="Discussion. [B](source:2)"),
                ClaimDiscussion(claim=2, discussion="More. [A](source:1)"),
            ],
        ),
        EMPTY_OVERVIEW_DEFECT,
        id="an empty overview",
    ),
    pytest.param(
        Analysis(
            language="en",
            overview="Overview without links.",
            claims=[
                ClaimDiscussion(claim=1, discussion="D."),
                ClaimDiscussion(claim=2, discussion="E."),
            ],
        ),
        NO_CITATION_DEFECT,
        id="an analysis with no citation",
    ),
]


def analysis() -> Analysis:
    """A valid analysis: every section cites the sources read, by number."""
    return Analysis(
        language="en",
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
    """Run `checked_answer` on `forecast_state`, with its analysis and final ballots."""
    forecast_state["analysis"] = analysis_ or analysis()
    forecast_state["final_ballots"] = final_ballots(
        forecast_state["ballots_round_1"], forecast_state["ballots_round_2"]
    )
    answer: str = verify_module.checked_answer(forecast_state)
    return answer


@pytest.mark.anyio
async def test_the_answer_renders_the_tally_and_every_vote(
    events: list[object],
) -> None:
    # Arrange
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
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
    events: list[object],
) -> None:
    # Arrange
    # Arrange
    forecast_state: Any = state(
        round_2={member: ballot(["for", "unsure"]) for member in range(1, 8)}
    )
    final = final_ballots(
        forecast_state["ballots_round_1"], forecast_state["ballots_round_2"]
    )
    forecast_state["tally"] = count_votes(2, final)
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = final
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert "Members voting: 7 of 7." in answer
    assert "unavailable" not in answer


@pytest.mark.anyio
async def test_a_reason_is_flattened_to_one_line(events: list[object]) -> None:
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
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "- Member 1: for — Line one. Line two, see (link removed) for more." in answer
    )
    assert "https://spam.example" not in answer


@pytest.mark.anyio
async def test_a_carried_vote_is_marked(events: list[object]) -> None:
    # Arrange
    # Arrange
    first = six_voters()
    second = {member: one for member, one in first.items() if member != 4}
    forecast_state: Any = state(round_1=first, round_2=second)
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = final_ballots(first, second)
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "Round 2: 1 of 6 kept their round-1 vote because they did not answer." in answer
    )
    assert "- Member 4 (round-1 vote): for — Reason 1." in answer


@pytest.mark.anyio
async def test_the_vote_list_shows_the_final_ballots_the_tally_stored(
    events: list[object],
) -> None:
    """The vote list reads the ballots `tally` stored, never a rebuild from the rounds."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = {**first, 2: ballot(["for", "unsure"])}
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert "- Member 2: for — Reason 1." in answer
    assert "- Member 2: against" not in answer


@pytest.mark.anyio
async def test_verify_checks_the_analysis_once(
    monkeypatch: pytest.MonkeyPatch, events: list[object]
) -> None:
    """The defect check runs once, in verify: a second run in the answer builder could drift from it."""
    # Arrange
    checks: list[Analysis] = []
    find_defect = verify_module.find_defect

    def counting_find_defect(analysis_: Analysis, *rest: Any) -> str | None:
        checks.append(analysis_)
        result: str | None = find_defect(analysis_, *rest)
        return result

    monkeypatch.setattr(verify_module, "find_defect", counting_find_defect)
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    # Act
    await verify_module.verify(forecast_state, runtime(events))
    # Assert
    assert len(checks) == 1


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
    line = verify_module.evidence_line(sources_, research_, claims_, "en")
    # Assert
    assert line.startswith(expected)


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
        language="en",
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
        language="en",
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


@pytest.mark.parametrize("link", ["[x](//evil.example)", "[x](ftp://evil.example)"])
def test_a_non_clickable_link_form_is_not_checked(link: str) -> None:
    """A link the chat UI cannot click stays unchecked: it renders as plain text."""
    # Arrange
    first = six_voters()
    forecast_state = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    analysis_ = Analysis(
        language="en",
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
    events: list[object],
) -> None:
    # Arrange
    # Act
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2={})
    forecast_state["tally"] = count_votes(2, first)
    forecast_state["analysis"] = analysis()
    forecast_state["final_ballots"] = final_ballots(first, {})
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    answer = out["answer"]
    assert (
        "Round 2: 6 of 6 kept their round-1 vote because they did not answer." in answer
    )
    for member in range(1, 7):
        assert f"- Member {member} (round-1 vote):" in answer


@pytest.mark.anyio
@pytest.mark.parametrize(("broken_analysis", "defect"), CHECKED_DEFECTS)
async def test_a_defect_sends_the_analysis_back_once(
    broken_analysis: Analysis, defect: str, events: list[object]
) -> None:
    """A defect the writer can fix goes back once, with the defect named."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = broken_analysis
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    assert out == {"feedback": defect}


@pytest.mark.anyio
@pytest.mark.parametrize(("broken_analysis", "defect"), CHECKED_DEFECTS)
async def test_a_defect_after_the_rewrite_is_a_hard_error(
    broken_analysis: Analysis, defect: str, events: list[object]
) -> None:
    """With the one rewrite spent, a defect is a hard 502 naming it, never a second send-back."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = broken_analysis
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    forecast_state["feedback"] = defect
    # Act + Assert
    with pytest.raises(LLMInvocationError) as raised:
        await verify_module.verify(forecast_state, runtime(events))
    assert raised.value.status == 502
    assert str(raised.value) == defect


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


@pytest.mark.parametrize(("broken_analysis", "_defect"), DEFECTS)
def test_a_defect_never_echoes_the_writers_text(
    broken_analysis: Analysis, _defect: str
) -> None:
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
async def test_a_first_defect_returns_feedback(events: list[object]) -> None:
    """On the analysis's first defect, verify sends it back once, named."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = MISSING_CLAIM
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    # Act
    out = await verify_module.verify(forecast_state, runtime(events))
    # Assert
    assert out == {"feedback": MISSING_CLAIM_DEFECT}
    assert "answer" not in out


@pytest.mark.anyio
async def test_a_second_defect_raises(events: list[object]) -> None:
    """With the one rewrite spent, a defect is a hard 502 naming the defect."""
    # Arrange
    first = six_voters()
    forecast_state: Any = state(round_1=first, round_2=dict(first))
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = MISSING_CLAIM
    forecast_state["final_ballots"] = final_ballots(first, dict(first))
    forecast_state["feedback"] = MISSING_CLAIM_DEFECT
    # Act + Assert
    with pytest.raises(LLMInvocationError) as raised:
        await verify_module.verify(forecast_state, runtime(events))
    assert raised.value.status == 502
    assert str(raised.value) == MISSING_CLAIM_DEFECT


@pytest.mark.anyio
async def test_a_polish_analysis_gets_a_polish_answer(events: list[object]) -> None:
    """A Polish reader must not meet English headings, verdicts, stances or dates."""
    # Arrange
    first = six_voters()
    second = {member: one for member, one in first.items() if member != 4}
    forecast_state: Any = state(round_1=first, round_2=second)
    forecast_state["tally"] = VOTING6_TALLY
    forecast_state["analysis"] = analysis().model_copy(update={"language": "pl"})
    forecast_state["final_ballots"] = final_ballots(first, second)

    # Act
    out = await verify_module.verify(forecast_state, runtime(events))

    # Assert
    answer = out["answer"]
    for part in (
        "## Twierdzenie 1: Alpha happens by 2027.",
        "Do 31 grudnia 2027. Werdykt rady: **PRZYJĘTE**",
        "## Jak głosowała rada",
        "Głosowało członków: 6 z 7 (niedostępnych: 1).",
        "Runda 2: członkowie, którzy zostali przy głosie z rundy 1, "
        "bo nie odpowiedzieli: 1 z 6.",
        "Dowody: przeczytane źródła: 2, witryny: 2.",
        "### Twierdzenie 1: PRZYJĘTE",
        "Za: 5, przeciw: 1, niepewnych: 0 (głosowało 6).",
        "- Członek 2: przeciw — Reason 1. ([Źródło 2](https://reuters.com/b))",
        "- Członek 4 (głos z rundy 1): za — Reason 1.",
    ):
        assert part in answer, part
    for english in ("Council verdict", "voted for", "- Member", "Evidence:"):
        assert english not in answer, english


def test_the_polish_evidence_line_reports_every_count() -> None:
    # Arrange
    sources_ = [
        Source("T", "https://forecasters.example/a", "Alpha."),
        Source("V", "https://www.youtube.com/watch?v=x", "Notes."),
    ]
    claims_ = [
        Claim(
            statement="S.",
            deadline=date(2027, 12, 31),
            evidence=[EvidenceRef(source=1, paragraph=1)],
        )
    ]
    research_ = ResearchOutcome(11, 3, True)

    # Act
    line = verify_module.evidence_line(sources_, research_, claims_, "pl")

    # Assert
    assert line == (
        "Dowody: przeczytane źródła: 2, witryny: 2, w tym notatki Gemini do wideo: 1. "
        "Rada głosowała na podstawie cytowanych fragmentów: 1, pochodzących z liczby "
        "źródeł: 1. Badanie zatrzymał limit czasu. Nieudane wyszukiwania: 3 z 11."
    )
