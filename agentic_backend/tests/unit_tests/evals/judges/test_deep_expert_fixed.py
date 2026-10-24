"""Unit tests for `evals.judges.deep_expert_fixed`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.deep_expert_fixed import (
    DEPTH_PROMPT,
    _depth_view,
    answer_without_closing_offer,
    answer_without_preamble,
    judges,
)

SOURCES = [{"title": "t", "url": "https://news.example/a", "text": "x"}]


def test_judges_names_are_the_experts_three_plus_depth() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert names == [
        "urls_from_sources",
        "answer_matches_expected",
        "faithful_to_sources",
        "answer_without_preamble",
        "answer_without_closing_offer",
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


def test_an_answer_that_opens_with_a_plan_fails() -> None:
    """A trace shipped an answer that opened with its own plan before any finding."""
    # Arrange
    answer = "## Plan and scope \u2014 what this note will (and will not) do\n\nThe deal sets 5%."

    # Act
    passed = answer_without_preamble({"answer": answer})

    # Assert
    assert passed is False


@pytest.mark.parametrize(
    "answer",
    [
        "Scope of the deal: members aim for 5% by 2035.",
        "Plan B failed because the vote slipped.",
    ],
    ids=["scope as a noun phrase", "plan as part of the story"],
)
def test_an_answer_that_opens_with_the_word_scope_or_plan_passes(answer: str) -> None:
    """The check targets a preamble heading, not any answer that starts with these words."""
    # Act
    passed = answer_without_preamble({"answer": answer})

    # Assert
    assert passed is True


def test_an_answer_that_quotes_the_assignment_fails() -> None:
    """Quoting the model's own instructions in the answer leaks the prompt to the reader."""
    # Arrange
    answer = "The deal sets 5%.\n\nThe assignment's rules require a second outlet."

    # Act
    passed = answer_without_preamble({"answer": answer})

    # Assert
    assert passed is False


def test_an_answer_about_the_rules_based_order_passes() -> None:
    """Ordinary geopolitics vocabulary must not be mistaken for a leaked instruction."""
    # Arrange
    answer = "The deal protects the rules-based international order."

    # Act
    passed = answer_without_preamble({"answer": answer})

    # Assert
    assert passed is True


def test_an_empty_answer_fails() -> None:
    """An empty answer has no opening and no ending, so both checks refuse it."""
    # Act
    results = (
        answer_without_preamble({"answer": ""}),
        answer_without_closing_offer({"answer": ""}),
    )

    # Assert
    assert results == (False, False)


def test_an_answer_that_closes_with_an_offer_fails() -> None:
    """A closing menu of next steps is a chat habit the analysis must not carry."""
    # Arrange
    answer = "The deal sets 5%.\n\nWhich next step would you like me to take?"

    # Act
    passed = answer_without_closing_offer({"answer": answer})

    # Assert
    assert passed is False


def test_an_answer_that_closes_with_analysis_passes() -> None:
    """An offer-like phrase earlier is not judged; only the last paragraph is."""
    # Arrange
    answer = (
        "Would you like the short version? No.\n\n"
        "The review of national plans is the only check on the 2035 target."
    )

    # Act
    passed = answer_without_closing_offer({"answer": answer})

    # Assert
    assert passed is True
