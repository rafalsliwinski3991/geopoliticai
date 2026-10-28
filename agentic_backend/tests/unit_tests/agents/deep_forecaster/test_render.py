"""Unit tests for `agents.deep_forecaster.render`."""

from datetime import date

import pytest

from agents.deep_forecaster.models import Ballot, Vote
from agents.deep_forecaster.render import (
    render_ballot,
    render_deadline,
    render_numbers,
    render_passages,
    render_reason,
    render_sources,
)
from models import Source
from unit_tests.agents.deep_forecaster.conftest import claims, sources

SOURCE_URL = "https://carnegieendowment.org/a"
URL_IN_TEXT = "https://x.example/memo"
URL_IN_TITLE = "https://x.example/title"
URL_IN_BYLINE = "https://x.example/author"


def test_render_deadline_is_in_full_words() -> None:
    # Assert
    assert render_deadline(date(2027, 12, 31)) == "31 December 2027"


def test_one_number_is_written_alone() -> None:
    # Arrange
    numbers = [3]
    # Act
    text = render_numbers(numbers)
    # Assert
    assert text == "3"


def test_two_numbers_are_joined_by_and() -> None:
    # Arrange
    numbers = [3, 5]
    # Act
    text = render_numbers(numbers)
    # Assert
    assert text == "3 and 5"


def test_three_numbers_use_commas_then_and() -> None:
    # Arrange
    numbers = [3, 5, 9]
    # Act
    text = render_numbers(numbers)
    # Assert
    assert text == "3, 5 and 9"


def test_no_numbers_render_as_an_empty_string() -> None:
    # Arrange
    numbers: list[int] = []
    # Act
    text = render_numbers(numbers)
    # Assert
    assert text == ""


def test_render_reason_removes_links_and_flattens() -> None:
    # Assert
    assert render_reason("See https://x.example/a and www.y.example\nnow") == (
        "See (link removed) and (link removed) now"
    )
    assert render_reason("[x](https://x.example/a)") == "[x]((link removed))"


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


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(SOURCE_URL, id="the metadata line"),
        pytest.param(URL_IN_TEXT, id="a URL inside the quoted text"),
        pytest.param(URL_IN_TITLE, id="a URL inside the title"),
        pytest.param(URL_IN_BYLINE, id="a URL inside the byline"),
    ],
)
def test_sources_render_without_urls_for_the_writer(url: str) -> None:
    """The writer's brief shows no URL anywhere: not the metadata line, and
    not a URL a title, byline or a source's own text carries, which
    `find_defect` would call a defect. The drafter keeps the default
    rendering, which still shows every URL.
    """
    # Arrange
    source = Source(
        f"A article, {URL_IN_TITLE}",
        SOURCE_URL,
        f"Alpha one. {URL_IN_TEXT}",
        author=f"Ann Author, {URL_IN_BYLINE}",
    )
    # Act
    rendered = render_sources([source], urls=False)
    default = render_sources([source])
    # Assert
    assert url not in rendered
    assert "[1.1] Alpha one. (link removed)" in rendered
    assert f"URL: {SOURCE_URL}" in default
    assert URL_IN_TEXT in default
    assert URL_IN_TITLE in default and URL_IN_BYLINE in default


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


def test_render_passages_names_each_claims_citable_sources() -> None:
    """Each claim's block ends with a "Cite only:" line naming the sources its
    passages quote: the rule `council.validate_ballot` enforces, stated where
    members read the passages, so a refusal names a rule the member read."""
    # Arrange
    # Act
    rendered = render_passages(claims(), sources())
    blocks = rendered.split("\n\n")
    claim_1 = next(block for block in blocks if block.startswith("Claim 1:"))
    claim_2 = next(block for block in blocks if block.startswith("Claim 2:"))
    # Assert: claim 1 quotes sources 1 and 2; claim 2 only source 1.
    assert claim_1.endswith("Cite only: Source 1, Source 2")
    assert claim_2.endswith("Cite only: Source 1")


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
