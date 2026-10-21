"""Unit tests for `evals.judges.expert_fixed` code checks and views."""

from __future__ import annotations

from evals.judges.expert_fixed import (
    ANSWER_PROMPT,
    _answer_view,
    _faithful_view,
    _urls_view,
)
from evals.judges.shared import FAITHFUL_PROMPT

SOURCES = [{"url": "https://news.example/1", "title": "t", "text": "x"}]


def test_urls_view_builds_variables_from_sources() -> None:
    # Arrange
    input = {"sources": SOURCES}
    output = {"answer": "Answer [a](https://news.example/1)."}

    # Act
    variables = _urls_view(input, output, {})

    # Assert
    assert variables == {
        "answer": "Answer [a](https://news.example/1).",
        "source_urls": ["https://news.example/1"],
    }


def test_the_answer_judge_applies_only_when_an_answer_is_expected() -> None:
    # Arrange: a case without `expected.answer` must not be graded against one.
    input = {"query": "q", "sources": SOURCES}
    output = {"answer": "A"}

    # Act
    unchecked = _answer_view(input, output, {"other": "x"})
    checked = _answer_view(input, output, {"answer": "E"})

    # Assert
    assert unchecked is None
    assert checked == {"question": "q", "actual": "A", "expected": "E"}


def test_the_faithful_view_says_so_when_the_answer_cites_no_recorded_page() -> None:
    """An empty sources block would let the judge score an answer against nothing."""
    # Arrange
    input = {"sources": SOURCES}
    output = {"answer": "No links here."}

    # Act
    variables = _faithful_view(input, output, {})

    # Assert
    assert variables == {
        "answer": "No links here.",
        "sources": "(the answer cites no recorded source)",
    }


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    input = {"query": "q", "sources": SOURCES}
    output = {"answer": "A [a](https://news.example/1)."}
    answer_variables = _answer_view(input, output, {"answer": "E"})
    faithful_variables = _faithful_view(input, output, {})
    assert answer_variables is not None

    # Act + Assert: str.format raises KeyError on a field the view leaves out.
    ANSWER_PROMPT.format(**answer_variables)
    FAITHFUL_PROMPT.format(**faithful_variables)
