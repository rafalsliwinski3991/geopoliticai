"""Unit tests for `evals.judges.expert` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.expert import _urls_view, judges, urls_from_sources


def _view_data(answer: str, source_urls: list[str]) -> dict[str, Any]:
    return {"answer": answer, "source_urls": source_urls}


def test_urls_from_sources_passes_on_subset() -> None:
    # Arrange
    variables = _view_data(
        "See [a](https://news.example/1) and [b](https://news.example/2).",
        ["https://news.example/1", "https://news.example/2", "https://news.example/3"],
    )

    # Act + Assert
    assert urls_from_sources(variables)


def test_urls_from_sources_fails_on_unknown_url() -> None:
    # Arrange
    variables = _view_data(
        "See [x](https://not-recorded.example/1).", ["https://news.example/1"]
    )

    # Act + Assert
    assert not urls_from_sources(variables)


def test_urls_from_sources_fails_with_no_links() -> None:
    # Arrange
    variables = _view_data("No links here.", ["https://news.example/1"])

    # Act + Assert
    assert not urls_from_sources(variables)


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


def test_judges_have_unique_names() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert len(names) == len(set(names))
