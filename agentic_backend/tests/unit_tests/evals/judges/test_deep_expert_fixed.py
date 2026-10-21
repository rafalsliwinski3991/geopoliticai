"""Unit tests for `evals.judges.deep_expert_fixed`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.deep_expert_fixed import DEPTH_PROMPT, _depth_view, judges

SOURCES = [{"title": "t", "url": "https://news.example/a", "text": "x"}]


def test_judges_names_are_the_experts_three_plus_depth() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert names == [
        "urls_from_sources",
        "answer_matches_expected",
        "faithful_to_sources",
        "deeper_than_expert",
    ]


def test_depth_view_requires_a_nonempty_expert_baseline() -> None:
    # Arrange: a missing (or empty) live expert baseline must fail loudly, not
    # become "", or any nonempty deep answer wins on depth by default.
    input: dict[str, Any] = {"query": "q"}
    for output in ({"answer": "D"}, {"answer": "D", "baseline_answer": ""}):
        # Act + Assert
        with pytest.raises(KeyError, match="baseline"):
            _depth_view(input, output, {})


def test_depth_view_maps_both_answers_when_the_baseline_exists() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "q"}
    output: dict[str, Any] = {"answer": "D", "baseline_answer": "S"}

    # Act
    variables = _depth_view(input, output, {})

    # Assert
    assert variables == {"question": "q", "deep_answer": "D", "answer": "S"}


def test_the_expert_judges_read_the_deep_answer() -> None:
    # Arrange: with one key vocabulary the deep answer is `answer`, so the
    # expert's own views need no adapter.
    output = {"answer": "A [x](https://news.example/a).", "baseline_answer": "S"}
    input = {"query": "q", "sources": SOURCES}

    # Act
    answer_view = judges()[1].view(input, output, {"answer": "E"})

    # Assert
    assert answer_view == {
        "question": "q",
        "actual": "A [x](https://news.example/a).",
        "expected": "E",
    }


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    variables = _depth_view({"query": "q"}, {"answer": "D", "baseline_answer": "S"}, {})

    # Act + Assert: str.format raises KeyError on a field the view leaves out.
    DEPTH_PROMPT.format(**variables)
