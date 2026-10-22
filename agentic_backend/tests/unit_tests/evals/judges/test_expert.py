"""Unit tests for `evals.judges.expert` code checks and views."""

from __future__ import annotations

from evals.judges.expert import _faithful_view, _urls_view, judges


def test_urls_view_builds_variables_from_sources() -> None:
    # Arrange
    input = {"sources": [{"url": "https://news.example/1", "title": "t", "text": "x"}]}
    output = {"answer": "Answer [a](https://news.example/1)."}

    # Act
    variables = _urls_view(input, output, {})

    # Assert
    assert variables == {
        "answer": "Answer [a](https://news.example/1).",
        "source_urls": ["https://news.example/1"],
    }


def test_the_faithful_view_says_so_when_the_answer_cites_no_recorded_page() -> None:
    """An empty sources block would let the judge score an answer against nothing."""
    # Arrange
    input = {"sources": [{"url": "https://news.example/1", "title": "t", "text": "x"}]}
    output = {"answer": "No links here."}

    # Act
    variables = _faithful_view(input, output, {})

    # Assert
    assert variables == {
        "answer": "No links here.",
        "sources": "(the answer cites no recorded source)",
    }


def test_judges_have_unique_names() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert len(names) == len(set(names))
