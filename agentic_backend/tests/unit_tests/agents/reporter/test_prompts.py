"""The reporter's prompts ignore the expert's closing next-step menu."""

import pytest

from agents.reporter.prompts import (
    OUTLINE_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    RESUME_INTENT_SYSTEM_PROMPT,
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


def test_the_outline_prompt_asks_to_cancel_and_quote_a_question() -> None:
    """The gate reads a typed line as a revision, so the notice must say to cancel and give a question."""
    # Arrange
    directives = [
        "that they should cancel this report",
        "one research question to ask next, in quotes, ending with a question mark",
        "never offer to retrieve, fetch or search for anything yourself",
    ]

    # Act
    missing = [
        d for d in directives if d not in OUTLINE_SYSTEM_PROMPT.replace("\\\n", "")
    ]

    # Assert
    assert missing == []


@pytest.mark.parametrize(
    ("prompt", "fragment"),
    [
        (OUTLINE_SYSTEM_PROMPT, "English or Polish"),
        (REPORT_SYSTEM_PROMPT, "English or Polish"),
        (RESUME_INTENT_SYSTEM_PROMPT, '"tak"'),
        (RESUME_INTENT_SYSTEM_PROMPT, '"nie"'),
        (RESUME_INTENT_SYSTEM_PROMPT, '"anuluj"'),
    ],
    ids=[
        "outline names both languages",
        "report names both languages",
        "resume reads tak",
        "resume reads nie",
        "resume reads anuluj",
    ],
)
def test_reporter_prompts_support_english_and_polish(
    prompt: str, fragment: str
) -> None:
    """A Polish request gets a Polish outline and report, and Polish replies are read."""
    # Act
    stated = fragment in prompt

    # Assert
    assert stated
