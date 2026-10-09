"""Unit tests for `agents.deep_forecaster.evidence`."""

from datetime import date

import agents.deep_forecaster.config as config
from agents.deep_forecaster.evidence import (
    links_in,
    paragraphs,
    quoted_sources,
    render_ballot,
    render_deadline,
    render_passages,
    render_reason,
    render_sources,
)
from agents.deep_forecaster.models import Ballot, Vote
from models import Source
from unit_tests.agents.deep_forecaster.conftest import claims, sources


def test_render_deadline_is_in_full_words() -> None:
    # Assert
    assert render_deadline(date(2027, 12, 31)) == "31 December 2027"


def test_render_reason_removes_links_and_flattens() -> None:
    # Assert
    assert render_reason("See https://x.example/a and www.y.example\nnow") == (
        "See (link removed) and (link removed) now"
    )
    assert render_reason("[x](https://x.example/a)") == "[x]((link removed))"


def test_links_in_collects_every_clickable_form() -> None:
    # Assert
    assert links_in(
        "[a](https://x.example/a), see https://y.example/b. And <https://z.example/c>"
    ) == [
        "https://x.example/a",
        "https://y.example/b",
        "https://z.example/c",
    ]


def test_sources_are_numbered_from_one_and_show_missing_bylines() -> None:
    # Arrange
    rendered = render_sources(sources())
    # Assert
    assert "--- SOURCE 1 ---" in rendered
    assert "--- SOURCE 2 ---" in rendered
    assert "Byline: Alexander Gabuev" in rendered
    assert "Byline: none" in rendered
    assert "[1.1] Alpha one." in rendered
    assert "[2.3] Beta three." in rendered


def test_paragraphs_are_the_non_blank_lines() -> None:
    # Assert
    assert paragraphs("  First  para.\n\n\nSecond\tone.\n   \n") == [
        "First para.",
        "Second one.",
    ]


def test_a_long_line_is_split_at_spaces() -> None:

    # Arrange
    limit = config.LIMITS.max_passage_chars
    words = ["word"] * 700
    line = " ".join(words)
    pieces = paragraphs(line)
    # Assert
    assert len(pieces) == 3
    assert all(len(piece) <= limit for piece in pieces)
    assert " ".join(pieces).split() == words


def test_a_long_line_without_spaces_is_cut_hard() -> None:

    # Arrange
    limit = config.LIMITS.max_passage_chars
    line = "x" * 2_600
    pieces = paragraphs(line)
    # Assert
    assert [len(piece) for piece in pieces] == [limit, limit, 2_600 - 2 * limit]


def test_render_sources_numbers_a_second_sources_paragraphs() -> None:
    # Arrange
    source = Source("t", "https://carnegieendowment.org/x", "a\nb")
    rendered = render_sources(
        [Source("t", "https://carnegieendowment.org/y", "z"), source]
    )
    # Assert
    assert "[2.1] a" in rendered
    assert "[2.2] b" in rendered


def test_render_passages_shows_only_the_quoted_paragraphs() -> None:
    # Arrange
    rendered = render_passages(claims(), sources())
    # Assert
    assert "Claim 1: Alpha happens by 2027. (deadline: 31 December 2027)" in rendered
    assert '- Source 1: "Alpha one."' in rendered
    assert '- Source 2: "Beta two."' in rendered
    assert '- Source 1: "Alpha three."' in rendered
    assert "Sources quoted:" in rendered
    assert "https://carnegieendowment.org/a" in rendered
    assert "Alpha two." not in rendered
    assert "Beta one." not in rendered
    assert "Beta three." not in rendered


def test_quoted_sources_is_the_union() -> None:
    # Assert
    assert quoted_sources(claims()) == frozenset({1, 2})


def test_ballot_lines_are_sorted_by_claim_and_cite_evidence() -> None:
    # Arrange
    ballot = Ballot(
        votes=[
            Vote(claim=2, stance="unsure", reason="Dunno.", evidence=[]),
            Vote(claim=1, stance="for", reason="Because.", evidence=[2, 3]),
        ]
    )
    rendered = render_ballot(ballot)
    # Assert
    assert rendered.index("Claim 1") < rendered.index("Claim 2")
    assert "(Sources 2, 3)" in rendered
    assert "Claim 2: unsure — Dunno." in rendered
