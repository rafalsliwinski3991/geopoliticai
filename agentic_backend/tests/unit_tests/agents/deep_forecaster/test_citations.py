"""Unit tests for `agents.deep_forecaster.citations`."""

import agents.deep_forecaster.config as config
from agents.deep_forecaster import citations
from agents.deep_forecaster.citations import (
    link_sources,
    links_in,
    paragraphs,
    quoted_sources,
)
from unit_tests.agents.deep_forecaster.conftest import claims, sources

SOURCE_URL = "https://carnegieendowment.org/a"
URL_IN_TEXT = "https://x.example/memo"
URL_IN_TITLE = "https://x.example/title"
URL_IN_BYLINE = "https://x.example/author"


def test_links_in_collects_every_clickable_form() -> None:
    # Assert
    assert links_in(
        "[a](https://x.example/a), see https://y.example/b. And <https://z.example/c>"
    ) == [
        "https://x.example/a",
        "https://y.example/b",
        "https://z.example/c",
    ]


def test_a_source_number_becomes_its_url() -> None:
    """A `(source:N)` citation points at source N's URL: code, never the writer, links.

    The writer cannot see a URL, so a correct citation can only name a number;
    the number is checked against the sources read before this substitution.
    """
    # Arrange
    # Act
    linked = link_sources("[A](source:2)", sources())
    # Assert
    assert linked == "[A](https://reuters.com/b)"


def test_source_link_returns_every_citation_as_written() -> None:
    """`verify` reads what each citation names as written, so any bad form is caught."""
    # Arrange
    # Act
    named = citations.SOURCE_LINK.findall("[A](source:1), [B](source:2), [C](source:x)")
    # Assert
    assert named == ["1", "2", "x"]


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


def test_quoted_sources_is_the_union() -> None:
    # Assert
    assert quoted_sources(claims()) == frozenset({1, 2})
