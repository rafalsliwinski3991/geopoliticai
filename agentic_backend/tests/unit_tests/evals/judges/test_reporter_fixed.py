"""Unit tests for `evals.judges.reporter_fixed` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.reporter_fixed import (
    OUTLINE_PROMPT,
    REPORT_PROMPT,
    _normalize_heading,
    _outcome_view,
    _outline_view,
    _reply_actions_view,
    _report_rules_view,
    _report_view,
    follows_outline,
    matches_expected,
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


def test_reply_actions_must_match_in_order() -> None:
    # Arrange
    expected = {"reply_actions": ["revise", "cancel"]}
    in_order = {"reply_actions": ["revise", "cancel"]}
    swapped = {"reply_actions": ["cancel", "revise"]}

    # Act
    same = _reply_actions_view({}, in_order, expected)
    different = _reply_actions_view({}, swapped, expected)

    # Assert
    assert same is not None and matches_expected(same)
    assert different is not None and not matches_expected(different)


def test_the_outcome_must_match() -> None:
    # Arrange
    expected = {"outcome": "cancelled"}

    # Act
    same = _outcome_view({}, {"outcome": "cancelled"}, expected)
    different = _outcome_view({}, {"outcome": "report"}, expected)

    # Assert
    assert same is not None and matches_expected(same)
    assert different is not None and not matches_expected(different)


def test_report_judges_apply_only_when_a_report_is_expected() -> None:
    # Arrange: a cancelled run ends with no report; its outline and report
    # are not graded.
    expected = {"outcome": "cancelled"}

    # Act + Assert
    assert _report_view({}, {}, expected) is None
    assert _outline_view({}, {}, expected) is None
    assert _report_rules_view({}, {}, expected) is None


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    input = {"replies": ["Looks good, write it."]}
    output = {
        "transcript": "User: q",
        "outline": ["Target"],
        "notice": "",
        "report": "# Report",
    }
    expected = {"outcome": "report"}
    outline_variables = _outline_view(input, output, expected)
    rules_variables = _report_rules_view(input, output, expected)
    assert outline_variables is not None
    assert rules_variables is not None

    # Act + Assert: str.format raises KeyError on a field the view leaves out.
    OUTLINE_PROMPT.format(**outline_variables)
    REPORT_PROMPT.format(**rules_variables)


def test_report_rules_view_builds_variables() -> None:
    # Act
    variables = _report_rules_view(
        input={},
        output={"transcript": "User: hi", "outline": ["Target"], "report": "# Report"},
        expected={"outcome": "report"},
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
