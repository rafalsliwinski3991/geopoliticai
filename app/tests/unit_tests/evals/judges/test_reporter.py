"""Unit tests for `evals.judges.reporter` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.reporter import (
    _normalize_heading,
    _outline_view,
    _report_rules_view,
    _report_view,
    follows_outline,
    judges,
    urls_from_transcript,
)


def _report_variables(report: str, outline: list[str]) -> dict[str, Any]:
    return {"report": report, "outline": outline, "transcript": ""}


def test_follows_outline_passes_on_exact_structure() -> None:
    # Arrange
    report = "# Report\n\n## Target\n\nText.\n\n## Funding\n\nMore."
    variables = _report_variables(report, ["Target", "Funding"])

    # Act + Assert
    assert follows_outline(variables)


def test_follows_outline_fails_on_dropped_heading() -> None:
    # Arrange
    report = "# Report\n\n## Target\n\nText.\n\n## Review\n\nMore."
    variables = _report_variables(report, ["Target", "Funding"])

    # Act + Assert
    assert follows_outline(variables) is False


def test_follows_outline_passes_on_normalized_headings() -> None:
    # Arrange
    report = "# Report\n\n## 1. **Spending target**:\n\nText.\n\n## Funding\n\nMore."
    variables = _report_variables(report, ["Spending target", "Funding"])

    # Act + Assert
    assert follows_outline(variables)


def test_follows_outline_fails_on_missing_title() -> None:
    # Arrange
    report = "## Target\n\nText.\n\n## Funding\n\nMore."
    variables = _report_variables(report, ["Target", "Funding"])

    # Act + Assert
    assert not follows_outline(variables)


def test_follows_outline_fails_on_two_titles() -> None:
    # Arrange
    report = "# One\n\n# Two\n\n## Target\n"
    variables = _report_variables(report, ["Target"])

    # Act + Assert
    assert not follows_outline(variables)


def test_follows_outline_fails_on_reordered_heading() -> None:
    # Arrange
    report = "# Report\n\n## Funding\n\nText.\n\n## Target\n\nMore."
    variables = _report_variables(report, ["Target", "Funding"])

    # Act + Assert
    assert not follows_outline(variables)


def test_follows_outline_fails_on_added_heading() -> None:
    # Arrange
    report = "# Report\n\n## Target\n\nText.\n\n## Extra\n\nMore."
    variables = _report_variables(report, ["Target"])

    # Act + Assert
    assert not follows_outline(variables)


def test_follows_outline_fails_on_empty_report() -> None:
    # Act + Assert
    assert not follows_outline(_report_variables("", ["Target"]))


def test_urls_from_transcript_passes_on_recorded_urls() -> None:
    # Arrange
    variables = {
        "transcript": "Assistant: see [a](https://news.example/1).",
        "report": "Report [a](https://news.example/1).",
    }

    # Act + Assert
    assert urls_from_transcript(variables)


def test_urls_from_transcript_passes_without_links_to_preserve() -> None:
    # Arrange: a transcript with no links carries nothing the report could drop.
    variables = {
        "transcript": "Assistant: no citations here.",
        "report": "Report without links.",
    }

    # Act + Assert
    assert urls_from_transcript(variables)


def test_urls_from_transcript_fails_when_every_citation_dropped() -> None:
    # Arrange
    variables = {
        "transcript": "Assistant: see [a](https://news.example/1).",
        "report": "Report with the citation stripped.",
    }

    # Act + Assert
    assert not urls_from_transcript(variables)


def test_urls_from_transcript_fails_on_unknown_url() -> None:
    # Arrange
    variables = {
        "transcript": "Assistant: see [a](https://news.example/1).",
        "report": "Report [a](https://other.example/1).",
    }

    # Act + Assert
    assert not urls_from_transcript(variables)


def test_urls_from_transcript_fails_on_truncated_url() -> None:
    # Arrange: a truncated target must not pass as a substring of the transcript URL.
    variables = {
        "transcript": "Assistant: see [a](https://news.example/1/full).",
        "report": "Report [a](https://news.example/1).",
    }

    # Act + Assert
    assert not urls_from_transcript(variables)


def test_report_view_returns_none_when_expected_report_empty() -> None:
    # Act + Assert
    assert _report_view({}, {}, {"report": ""}) is None
    assert _report_rules_view({}, {}, {"report": ""}) is None


def test_outline_view_returns_none_when_expected_outline_empty() -> None:
    # Arrange: a refusal or revision-cap outcome ends with an empty outline
    # and a notice; the grounded-outline judge does not apply to it.
    # Act + Assert
    assert _outline_view({}, {}, {"outline": []}) is None
    assert _outline_view({}, {}, {"outline": [], "notice": "no material"}) is None


def test_report_rules_view_builds_variables() -> None:
    # Act
    variables = _report_rules_view(
        input={"transcript": "User: hi"},
        output={"outline": ["Target"], "report": "# Report"},
        expected={"report": "yes"},
    )

    # Assert
    assert variables == {
        "transcript": "User: hi",
        "outline": "Target",
        "report": "# Report",
    }


def test_normalize_heading_strips_noise() -> None:
    # Assert
    assert _normalize_heading("1. **Spending target**: ") == "spending target"
    assert _normalize_heading("Spending Target") == "spending target"


def test_judges_have_unique_names() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert len(names) == len(set(names))
