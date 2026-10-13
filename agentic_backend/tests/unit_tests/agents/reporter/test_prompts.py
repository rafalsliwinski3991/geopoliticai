"""The reporter's prompts ignore the expert's closing next-step menu."""

from agents.reporter.prompts import (
    OUTLINE_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
)


def test_outline_prompt_ignores_closing_menus() -> None:
    # Arrange
    ignore_rule = "closing menu of next steps"

    # Act
    in_outline = ignore_rule in OUTLINE_SYSTEM_PROMPT

    # Assert
    assert in_outline


def test_report_prompt_ignores_closing_menus() -> None:
    # Arrange
    ignore_rule = "closing menu of next steps"

    # Act
    in_report = ignore_rule in REPORT_SYSTEM_PROMPT

    # Assert
    assert in_report
