"""The reporter's prompts ignore the expert's closing next-step menu."""

import importlib

prompts = importlib.import_module("agents.reporter.prompts")


def test_outline_prompt_ignores_closing_menus() -> None:
    # Arrange
    ignore_rule = "closing menu of next steps"

    # Act
    in_outline = ignore_rule in prompts.OUTLINE_SYSTEM_PROMPT

    # Assert
    assert in_outline


def test_report_prompt_ignores_closing_menus() -> None:
    # Arrange
    ignore_rule = "closing menu of next steps"

    # Act
    in_report = ignore_rule in prompts.REPORT_SYSTEM_PROMPT

    # Assert
    assert in_report
