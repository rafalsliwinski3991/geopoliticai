"""The reporter's prompts ignore the expert's closing next-step menu."""

from agents.reporter.prompts import (
    OUTLINE_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
)


def test_outline_prompt_ignores_closing_menus() -> None:
    # Arrange
    directive = "never propose a section for it"

    # Act
    in_outline = directive in OUTLINE_SYSTEM_PROMPT

    # Assert
    assert in_outline


def test_report_prompt_ignores_closing_menus() -> None:
    # Arrange
    directive = "leave it out of the report"

    # Act
    in_report = directive in REPORT_SYSTEM_PROMPT

    # Assert
    assert in_report
