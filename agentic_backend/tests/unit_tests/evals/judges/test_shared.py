"""Unit tests for `evals.judges.shared`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.shared import (
    build_outcome_judge,
    finished_or_outside,
    render_cited_sources,
    skip_unless_finished,
    urls_from_sources,
)


def _view_data(answer: str, source_urls: list[str]) -> dict[str, Any]:
    return {"answer": answer, "source_urls": source_urls}


def test_an_answer_linking_only_pages_the_run_read_passes() -> None:
    # Arrange
    variables = _view_data(
        "See [a](https://news.example/1) and [b](https://news.example/2).",
        ["https://news.example/1", "https://news.example/2", "https://news.example/3"],
    )

    # Act
    passed = urls_from_sources(variables)

    # Assert
    assert passed


def test_an_answer_linking_a_page_the_run_never_read_fails() -> None:
    # Arrange
    variables = _view_data(
        "See [x](https://not-recorded.example/1).", ["https://news.example/1"]
    )

    # Act
    passed = urls_from_sources(variables)

    # Assert
    assert not passed


def test_one_unread_link_fails_an_answer_whose_other_links_were_read() -> None:
    """Every link must be one the run read; one good link does not carry a bad one."""
    # Arrange
    variables = _view_data(
        "See [a](https://news.example/1) and [x](https://not-recorded.example/1).",
        ["https://news.example/1"],
    )

    # Act
    passed = urls_from_sources(variables)

    # Assert
    assert not passed


def test_an_answer_with_no_links_fails() -> None:
    # Arrange
    variables = _view_data("No links here.", ["https://news.example/1"])

    # Act
    passed = urls_from_sources(variables)

    # Assert
    assert not passed


@pytest.mark.parametrize(
    ("variables", "verdict"),
    [
        pytest.param({"finished": True, "side": ""}, True, id="finished"),
        pytest.param({"finished": False, "side": "outside"}, True, id="failed outside"),
        pytest.param({"finished": False, "side": "ours"}, False, id="failed ours"),
    ],
)
def test_finished_or_outside(variables: dict[str, Any], verdict: bool) -> None:
    # Arrange: `variables` comes from the parametrization above — a finished
    # row, a provider outage, or a failure of ours.
    # Act
    result = finished_or_outside(variables)
    # Assert
    assert result is verdict


def test_cited_sources_keep_only_the_pages_the_answer_links() -> None:
    """The faithfulness judge reads only the pages the answer cites, not every page the run read."""
    # Arrange
    sources = [
        {"url": "https://news.example/1", "title": "One", "text": "first text"},
        {"url": "https://news.example/2", "title": "Two", "text": "second text"},
    ]
    answer = "See [one](https://news.example/1)."
    # Act
    rendered = render_cited_sources(sources, answer)
    # Assert
    assert rendered == "SOURCE https://news.example/1\nOne\nfirst text"


def test_cited_sources_follow_the_run_order_and_are_joined_by_a_blank_line() -> None:
    """The judge reads pages in the order the run read them, whatever order the answer links them."""
    # Arrange
    sources = [
        {"url": "https://news.example/1", "title": "One", "text": "first text"},
        {"url": "https://news.example/2", "title": "Two", "text": "second text"},
    ]
    answer = "See [two](https://news.example/2) and [one](https://news.example/1)."
    # Act
    rendered = render_cited_sources(sources, answer)
    # Assert
    assert rendered == (
        "SOURCE https://news.example/1\nOne\nfirst text\n\n"
        "SOURCE https://news.example/2\nTwo\nsecond text"
    )


def test_cited_sources_are_empty_when_the_answer_links_none() -> None:
    """An answer with no links cites nothing, so no page text reaches the judge."""
    # Arrange
    sources = [{"url": "https://news.example/1", "title": "One", "text": "first text"}]
    # Act
    rendered = render_cited_sources(sources, "No links here.")
    # Assert
    assert rendered == ""


def test_a_gated_view_skips_a_run_that_did_not_finish() -> None:
    """A live run that failed must not also fail every answer judge."""
    # Arrange
    calls: list[dict[str, Any]] = []

    def view(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any] | None:
        calls.append(output)
        return {"read": True}

    gated = skip_unless_finished(view)
    # Act
    variables = gated({}, {"finished": False}, {})
    # Assert
    assert variables is None
    assert calls == []


def test_a_gated_view_reads_a_finished_run() -> None:
    """A finished run reaches the wrapped view, and its variables come back unchanged."""

    # Arrange
    def view(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any] | None:
        return {
            "query": input["query"],
            "answer": output["answer"],
            "expected": expected["answer"],
        }

    gated = skip_unless_finished(view)
    # Act
    variables = gated(
        {"query": "Q"}, {"finished": True, "answer": "A"}, {"answer": "E"}
    )
    # Assert: the wrapped view received all three arguments unchanged.
    assert variables == {"query": "Q", "answer": "A", "expected": "E"}


def test_the_outcome_judge_skips_an_output_without_a_finish_flag() -> None:
    """The dataset's own empty output has no run to judge, so the outcome judge declines it."""
    # Arrange
    judge = build_outcome_judge()
    # Act
    variables = judge.view({}, {}, {})
    # Assert
    assert variables is None
