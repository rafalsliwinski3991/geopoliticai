"""Unit tests for `agents.deep_forecaster.prompts`."""

from agents.deep_forecaster.prompts import (
    _UNTRUSTED_RULE,
    LEAD_SYSTEM_PROMPT,
    SCOUT_PROMPT,
    VIDEO_NOT_DISCUSSED,
    VIDEO_PROMPT,
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
    assert _UNTRUSTED_RULE in LEAD_SYSTEM_PROMPT
    assert _UNTRUSTED_RULE in SCOUT_PROMPT


def test_video_prompt_names_the_not_discussed_reply() -> None:
    filled = VIDEO_PROMPT.format(
        question="Russia and NATO", not_discussed=VIDEO_NOT_DISCUSSED
    )
    assert VIDEO_NOT_DISCUSSED in filled


def test_lead_prompt_delegates_with_the_task_tool() -> None:
    assert "Delegate with the `task` tool" in LEAD_SYSTEM_PROMPT
