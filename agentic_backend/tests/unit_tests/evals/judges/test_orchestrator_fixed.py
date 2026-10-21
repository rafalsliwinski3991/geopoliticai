"""Unit tests for `evals.judges.orchestrator_fixed` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.orchestrator_fixed import (
    QUERY_PROMPT,
    _query_view,
    _routing_view,
    routing_correct,
)

CONVERSATION = {
    "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello there"},
    ]
}


def _variables(actual: object, expected: object) -> dict[str, Any]:
    return {"actual": actual, "expected": expected}


def test_routing_correct_passes_on_same_destination() -> None:
    # Act + Assert
    assert routing_correct(_variables("geopolitical", "geopolitical"))


def test_routing_correct_fails_on_different_destination() -> None:
    # Act + Assert
    assert not routing_correct(_variables("other", "geopolitical"))


def test_routing_is_checked_only_when_expected() -> None:
    # Arrange: a case that leaves `destination` out must not be graded on it.
    output = {"destination": "other"}

    # Act
    unchecked = _routing_view(CONVERSATION, output, {"standalone_query": "q"})
    checked = _routing_view(CONVERSATION, output, {"destination": "other"})

    # Assert
    assert unchecked is None
    assert checked == {"actual": "other", "expected": "other"}


def test_the_rewrite_is_checked_only_when_expected() -> None:
    # Arrange: the dataset expects a rewrite only on the research routes.
    output = {"standalone_query": "What is the target?"}

    # Act
    unchecked = _query_view(CONVERSATION, output, {"destination": "report"})
    checked = _query_view(
        CONVERSATION,
        output,
        {"destination": "deep", "standalone_query": "What is the 5% target?"},
    )

    # Assert
    assert unchecked is None
    assert checked == {
        "conversation": "user: hi\nassistant: hello there",
        "actual": "What is the target?",
        "expected": "What is the 5% target?",
    }


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    variables = _query_view(
        CONVERSATION, {"standalone_query": "q"}, {"standalone_query": "e"}
    )
    assert variables is not None

    # Act + Assert: str.format raises KeyError on a field the view leaves out.
    QUERY_PROMPT.format(**variables)
