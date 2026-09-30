"""Unit tests for `evals.judges.deep_expert`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.deep_expert import _depth_view, judges


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
    for output in ({"deep_answer": "D"}, {"deep_answer": "D", "answer": ""}):
        # Act + Assert
        with pytest.raises(KeyError, match="baseline"):
            _depth_view(input, output, {})


def test_depth_view_maps_both_answers_when_the_baseline_exists() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "q"}
    output: dict[str, Any] = {"deep_answer": "D", "answer": "S"}

    # Act
    variables = _depth_view(input, output, {})

    # Assert
    assert variables == {"question": "q", "deep_answer": "D", "answer": "S"}


def test_the_adapted_expert_judges_read_the_deep_answer_never_the_expert_answer() -> (
    None
):
    # Arrange
    adapted = judges()
    output = {
        "deep_answer": "A [x](https://news.example/a).",
        "answer": "S",
    }
    expected = {"deep_answer": "E"}

    # Act: answer_matches_expected's view
    answer_view = adapted[1].view({"query": "q"}, output, expected)

    # Assert
    assert answer_view == {
        "question": "q",
        "actual": "A [x](https://news.example/a).",
        "expected": "E",
    }

    # The expert's own answer "S" must appear in no adapted view's variables.
    # (The depth judge reads both answers on purpose; it is not an adapter.)
    for judge in adapted[:3]:
        view = judge.view(
            {
                "query": "q",
                "sources": [
                    {"title": "t", "url": "https://news.example/a", "text": "x"}
                ],
            },
            output,
            expected,
        )
        if view is None:
            continue
        assert "S" not in view.values()


def test_urls_from_sources_passes_through_the_adapter() -> None:
    # Arrange
    adapted = judges()
    output = {"deep_answer": "A [x](https://news.example/a)."}
    expected = {"deep_answer": "E"}
    input = {
        "sources": [{"title": "t", "url": "https://news.example/a", "text": "x"}],
    }

    # Act
    variables = adapted[0].view(input, output, expected)

    # Assert
    assert variables == {
        "answer": "A [x](https://news.example/a).",
        "source_urls": ["https://news.example/a"],
    }
    assert adapted[0].check is not None
