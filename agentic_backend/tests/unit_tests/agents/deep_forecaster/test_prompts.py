"""Unit tests for `agents.deep_forecaster.prompts`."""

from agents.deep_forecaster.prompts import (
    _UNTRUSTED_RULE,
    DRAFT_CLAIMS_PROMPT,
    LEAD_SYSTEM_PROMPT,
    MEMBER_SYSTEM_PROMPT,
    RETRY_INSTRUCTIONS,
    ROUND_TWO_INSTRUCTIONS,
    SCOUT_PROMPT,
    VIDEO_NOT_DISCUSSED,
    VIDEO_PROMPT,
    WRITE_SYSTEM_PROMPT,
)


def test_every_template_fills_with_its_documented_fields() -> None:
    # Raises nothing and leaves no `{`.
    lead = LEAD_SYSTEM_PROMPT.format(
        forecasters="- wojczal: Wojczal, focus",
        max_searches=1,
        max_sources=1,
        max_videos=1,
    )
    video = VIDEO_PROMPT.format(
        question="Russia and NATO", not_discussed=VIDEO_NOT_DISCUSSED
    )
    for text in (lead, SCOUT_PROMPT, video):
        assert "{" not in text, text


def test_every_prompt_that_reads_pages_carries_the_untrusted_rule() -> None:
    # Assert
    assert _UNTRUSTED_RULE in LEAD_SYSTEM_PROMPT
    assert _UNTRUSTED_RULE in SCOUT_PROMPT


def test_video_prompt_names_the_not_discussed_reply() -> None:
    # Arrange
    filled = VIDEO_PROMPT.format(
        question="Russia and NATO", not_discussed=VIDEO_NOT_DISCUSSED
    )
    # Assert
    assert VIDEO_NOT_DISCUSSED in filled


def test_lead_prompt_delegates_with_the_task_tool() -> None:
    # Assert
    assert "Delegate with the `task` tool" in LEAD_SYSTEM_PROMPT


def test_the_write_prompt_fills_with_today_and_carries_the_untrusted_rule() -> None:
    filled = WRITE_SYSTEM_PROMPT.format(today="30 September 2026")
    assert "{" not in filled, filled
    assert _UNTRUSTED_RULE in WRITE_SYSTEM_PROMPT
    assert DRAFT_CLAIMS_PROMPT.format(today="30 September 2026")
    assert _UNTRUSTED_RULE in MEMBER_SYSTEM_PROMPT
    assert "Round 2" in ROUND_TWO_INSTRUCTIONS


def test_the_write_prompt_asks_for_source_numbers() -> None:
    """The writer cites `[anchor](source:N)`: it never sees a URL to copy."""
    # Act + Assert
    assert "(source:3)" in WRITE_SYSTEM_PROMPT
    assert "Copy the URL" not in WRITE_SYSTEM_PROMPT


def test_the_retry_instructions_fill_with_the_defect() -> None:
    """The rewrite prompt fills with the defect and leaks no template braces."""
    # Arrange
    defect = "claim 9 is missing"

    # Act
    filled = RETRY_INSTRUCTIONS.format(defect=defect)

    # Assert
    assert defect in filled
    assert "{" not in filled
