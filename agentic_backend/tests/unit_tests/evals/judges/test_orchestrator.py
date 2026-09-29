"""Unit tests for `evals.judges.orchestrator` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.orchestrator import (
    _chat_view,
    _query_view,
    chat_no_links,
    judges,
    routing_correct,
)


def _variables(actual: object, expected: object) -> dict[str, Any]:
    return {"actual": actual, "expected": expected}


def test_routing_correct_passes_on_same_destination() -> None:
    # Act + Assert
    assert routing_correct(_variables("geopolitical", "geopolitical"))


def test_routing_correct_fails_on_different_destination() -> None:
    # Act + Assert
    assert not routing_correct(_variables("other", "geopolitical"))


def test_chat_no_links_passes_on_plain_text() -> None:
    # Act + Assert
    assert chat_no_links(_variables("Hello! How can I help?", "expected"))


def test_chat_no_links_fails_on_markdown_link() -> None:
    # Act + Assert
    assert not chat_no_links(_variables("See [x](https://a.b) for that.", "expected"))


def test_chat_no_links_fails_on_bare_url() -> None:
    # Act + Assert
    assert not chat_no_links(_variables("Read https://a.b/story for that.", "expected"))


def test_chat_no_links_fails_on_autolink() -> None:
    # Act + Assert
    assert not chat_no_links(
        _variables("See <https://a.b/story> for that.", "expected")
    )


def test_chat_no_links_fails_on_empty_answer() -> None:
    # Act + Assert
    assert not chat_no_links(_variables("", "expected"))


def test_chat_view_returns_none_for_non_chat_destination() -> None:
    # Act
    variables = _chat_view(
        input={"messages": []},
        output={"answer": "hi"},
        expected={"destination": "geopolitical", "answer": "expected"},
    )

    # Assert
    assert variables is None


def test_chat_view_builds_conversation_for_chat_destination() -> None:
    # Arrange
    input = {
        "messages": [
            {"type": "human", "data": {"type": "human", "content": "hi"}},
            {"type": "ai", "data": {"type": "ai", "content": "hello there"}},
        ]
    }

    # Act
    variables = _chat_view(
        input=input,
        output={"answer": "actual answer"},
        expected={"destination": "other", "answer": "expected answer"},
    )

    # Assert
    assert variables == {
        "conversation": "human: hi\nai: hello there",
        "actual": "actual answer",
        "expected": "expected answer",
    }


def test_judges_have_unique_names() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert len(names) == len(set(names))


def test_query_view_applies_to_deep_and_not_to_report() -> None:
    # Arrange
    input: dict[str, Any] = {
        "messages": [{"type": "human", "data": {"type": "human", "content": "hi"}}]
    }

    # Act + Assert
    assert (
        _query_view(input, {}, {"destination": "deep", "standalone_query": "q"})
        is not None
    )
    assert _query_view(input, {}, {"destination": "report"}) is None
