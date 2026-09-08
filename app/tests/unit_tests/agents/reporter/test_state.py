import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from agents.reporter.state import (
    build_initial_reporter_state,
    build_transcript,
    has_researched_material,
)


def test_transcript_renders_roles_chronologically_joined_by_blank_lines() -> None:
    messages: list[AnyMessage] = [
        HumanMessage("What is happening on NATO's eastern flank?"),
        AIMessage("Here is a briefing with a citation [1](https://example.com/a)."),
        HumanMessage("And what about Poland?"),
        AIMessage("Poland is covered here [2](https://example.com/b)."),
    ]

    transcript = build_transcript(messages)

    assert transcript == (
        "User: What is happening on NATO's eastern flank?\n\n"
        "Assistant: Here is a briefing with a citation [1](https://example.com/a).\n\n"
        "User: And what about Poland?\n\n"
        "Assistant: Poland is covered here [2](https://example.com/b)."
    )


def test_budget_keeps_the_newest_messages_and_drops_the_oldest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Budget 80: the two newest blocks (39 + 35 chars) fit whole, the oldest
    # (40 chars) does not. Asserted by content, not by length.
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", 80)
    messages: list[AnyMessage] = [
        AIMessage("Oldest answer, dropped whole."),
        HumanMessage("Newer question that survives."),
        AIMessage("Newest answer that survives."),
    ]

    transcript = build_transcript(messages)

    assert transcript == (
        "User: Newer question that survives.\n\nAssistant: Newest answer that survives."
    )


def test_a_message_that_would_straddle_the_budget_is_dropped_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Budget 50: the newest block (39 chars) leaves 11, the next block needs
    # more, so it is dropped whole and the walk stops.
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", 50)
    messages: list[AnyMessage] = [
        AIMessage("Oldest answer, dropped whole."),
        HumanMessage("A question whose block would straddle the character budget."),
        AIMessage("Newest answer that survives."),
    ]

    transcript = build_transcript(messages)

    assert transcript == "Assistant: Newest answer that survives."
    assert "straddle" not in transcript


def test_empty_and_whitespace_only_messages_are_skipped_without_consuming_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The budget is exactly the length of the one real block: if the two
    # empty messages consumed any of it, that block would not fit.
    real_block = "Assistant: Newest answer that survives."
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", len(real_block))
    messages: list[AnyMessage] = [
        HumanMessage("  \n\t "),
        AIMessage(""),
        AIMessage("Newest answer that survives."),
    ]

    assert build_transcript(messages) == real_block


def test_build_initial_state_starts_empty_without_raising() -> None:
    state = build_initial_reporter_state("")

    assert state["revisions"] == 0
    assert state["outline"] == []


def test_an_expert_answer_with_a_citation_has_researched_material() -> None:
    messages = [AIMessage("The shift is documented [1](https://example.com/a).")]

    assert has_researched_material(messages) is True


def test_a_chat_only_thread_has_no_researched_material() -> None:
    messages: list[AnyMessage] = [
        HumanMessage("Hello!"),
        AIMessage("Hi there. What would you like to talk about?"),
    ]

    assert has_researched_material(messages) is False


def test_a_link_in_a_user_message_does_not_count_as_material() -> None:
    messages: list[AnyMessage] = [
        HumanMessage("Look at this: [source](https://example.com/pasted)."),
        AIMessage("Thanks, I will take a look."),
    ]

    assert has_researched_material(messages) is False


def test_an_empty_thread_has_no_researched_material() -> None:
    assert has_researched_material([]) is False


def test_a_chat_answer_with_a_link_passes_the_material_gate() -> None:
    # Known false positive (plan §7 Q-F): `has_researched_material` is a
    # proxy, not a proof. A chat answer that emits a markdown link despite
    # CHAT_SYSTEM_PROMPT rule 1 — echoing a URL the user pasted, say —
    # passes this gate. Asserted here so the trade-off stays a recorded
    # decision rather than an apparent bug.
    messages: list[AnyMessage] = [
        HumanMessage("Can you paste that source link again?"),
        AIMessage("Sure: [the source](https://example.com/pasted-back)."),
    ]

    assert has_researched_material(messages) is True
