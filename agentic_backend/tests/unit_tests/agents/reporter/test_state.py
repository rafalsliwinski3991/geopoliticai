import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from pydantic import Field, create_model

from agents.reporter.state import (
    OutlineDraft,
    build_initial_reporter_state,
    build_transcript,
    has_researched_material,
)


def test_transcript_renders_roles_chronologically_joined_by_blank_lines() -> None:
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("What is happening on NATO's eastern flank?"),
        AIMessage("Here is a briefing with a citation [1](https://example.com/a)."),
        HumanMessage("And what about Poland?"),
        AIMessage("Poland is covered here [2](https://example.com/b)."),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == (
        "User: What is happening on NATO's eastern flank?\n\n"
        "Assistant: Here is a briefing with a citation [1](https://example.com/a).\n\n"
        "User: And what about Poland?\n\n"
        "Assistant: Poland is covered here [2](https://example.com/b)."
    )


def test_budget_keeps_the_newest_messages_and_drops_the_oldest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # Budget 80: the two newest blocks (39 + 35 chars) fit whole, the oldest
    # (40 chars) does not. Asserted by content, not by length.
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", 80)
    messages: list[AnyMessage] = [
        AIMessage("Oldest answer, dropped whole."),
        HumanMessage("Newer question that survives."),
        AIMessage("Newest answer that survives."),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == (
        "User: Newer question that survives.\n\nAssistant: Newest answer that survives."
    )


def test_a_message_that_would_straddle_the_budget_is_dropped_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # Budget 50: the newest block (39 chars) leaves 11, the next block needs
    # more, so it is dropped whole and the walk stops.
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", 50)
    messages: list[AnyMessage] = [
        AIMessage("Oldest answer, dropped whole."),
        HumanMessage("A question whose block would straddle the character budget."),
        AIMessage("Newest answer that survives."),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == "Assistant: Newest answer that survives."
    assert "straddle" not in transcript


def test_empty_and_whitespace_only_messages_are_skipped_without_consuming_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    # The budget is exactly the length of the one real block: if the two
    # empty messages consumed any of it, that block would not fit.
    real_block = "Assistant: Newest answer that survives."
    monkeypatch.setattr("agents.reporter.state.MAX_TRANSCRIPT_CHARS", len(real_block))
    messages: list[AnyMessage] = [
        HumanMessage("  \n\t "),
        AIMessage(""),
        AIMessage("Newest answer that survives."),
    ]

    # Act + Assert
    assert build_transcript(messages) == real_block


def test_build_initial_state_starts_empty_without_raising() -> None:
    # Act
    state = build_initial_reporter_state("")

    # Assert
    assert state["revisions"] == 0
    assert state["outline"] == []


def test_an_expert_answer_with_a_citation_has_researched_material() -> None:
    # Arrange
    messages = [AIMessage("The shift is documented [1](https://example.com/a).")]

    # Act + Assert
    assert has_researched_material(messages) is True


def test_a_chat_only_thread_has_no_researched_material() -> None:
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Hello!"),
        AIMessage("Hi there. What would you like to talk about?"),
    ]

    # Act + Assert
    assert has_researched_material(messages) is False


def test_a_link_in_a_user_message_does_not_count_as_material() -> None:
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Look at this: [source](https://example.com/pasted)."),
        AIMessage("Thanks, I will take a look."),
    ]

    # Act + Assert
    assert has_researched_material(messages) is False


def test_an_empty_thread_has_no_researched_material() -> None:
    # Act + Assert
    assert has_researched_material([]) is False


def test_a_chat_answer_with_a_link_passes_the_material_gate() -> None:
    # Arrange
    # Known false positive (plan §7 Q-F): `has_researched_material` is a
    # proxy, not a proof. A chat answer that emits a markdown link despite
    # the supervisor prompt's rule 1 (echoing a URL the user pasted, say)
    # passes this gate. Asserted here so the trade-off stays a recorded
    # decision rather than an apparent bug.
    messages: list[AnyMessage] = [
        HumanMessage("Can you paste that source link again?"),
        AIMessage("Sure: [the source](https://example.com/pasted-back)."),
    ]

    # Act + Assert
    assert has_researched_material(messages) is True


def test_the_outline_schema_is_a_plain_string_field() -> None:
    # Arrange
    # The strict structured-output call sends this schema to the model. A twin
    # with plain `str` fields must produce the same schema, or the annotation
    # changed what the model is asked for.
    plain = create_model(
        "PlainOutlineDraft",
        __doc__=OutlineDraft.__doc__,
        sections=(
            list[str],
            Field(description=OutlineDraft.model_fields["sections"].description),
        ),
        notice=(
            str,
            Field(description=OutlineDraft.model_fields["notice"].description),
        ),
    )

    # Act
    schema = OutlineDraft.model_json_schema()
    twin = plain.model_json_schema()

    # Assert
    del schema["title"], twin["title"]
    assert schema == twin


def test_transcript_extracts_full_text_from_tool_message_artifact() -> None:
    """Specialist tools return short summary content but attach the complete research
    text in artifact['text']. The transcript extractor must read the artifact so
    downstream report generation sees the full research.
    """
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("What is the Baltic situation?"),
        ToolMessage(
            content="Synthesized verified research on 'Baltic situation' from 2 sources.",
            tool_call_id="call_expert_1",
            artifact={
                "text": "Detailed Baltic briefing [1](https://example.com/baltic)."
            },
        ),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == (
        "User: What is the Baltic situation?\n\n"
        "Assistant: Detailed Baltic briefing [1](https://example.com/baltic)."
    )


def test_transcript_falls_back_to_tool_message_content_when_artifact_is_not_dict() -> (
    None
):
    """When a ToolMessage has no artifact or a non-dict artifact, the extractor must
    fall back to content so research text is not silently dropped.
    """
    # Arrange
    messages: list[AnyMessage] = [
        ToolMessage(
            content="Fallback content without artifact.",
            tool_call_id="call_fallback",
            artifact="not a dict",
        ),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == "Assistant: Fallback content without artifact."


def test_transcript_skips_tool_calling_ai_messages() -> None:
    """Assistant messages initiating tool calls contain function schemas rather than
    conversational research text. The transcript must omit them to avoid leaking tool schemas.
    """
    # Arrange
    messages: list[AnyMessage] = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": "NATO"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="Done",
            tool_call_id="call_1",
            artifact={"text": "Verified research content."},
        ),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == "Assistant: Verified research content."
    assert "run_expert" not in transcript


def test_transcript_skips_footer_ai_messages() -> None:
    """Assistant footer messages starting with '\\n\\n---\\n' are UI display metadata rather
    than narrative content. The transcript must skip them to keep the report clean.
    """
    # Arrange
    messages: list[AnyMessage] = [
        AIMessage("Main answer text."),
        AIMessage("\n\n---\n**Sources**: [Example](https://example.com)"),
    ]

    # Act
    transcript = build_transcript(messages)

    # Assert
    assert transcript == "Assistant: Main answer text."
    assert "Sources" not in transcript


def test_has_researched_material_returns_true_when_workspace_synthesis_is_present() -> (
    None
):
    """When the multi-agent workspace contains expert synthesis strings, the reporter has
    research material to synthesize even if messages contain no inline links.
    """
    # Arrange
    messages: list[AnyMessage] = [HumanMessage("Tell me about the treaties")]
    synthesis = ["Synthesized analysis of the treaties."]

    # Act + Assert
    assert has_researched_material(messages, workspace_synthesis=synthesis) is True


def test_has_researched_material_returns_true_when_workspace_forecasts_are_present() -> (
    None
):
    """When the workspace contains forecast entries, the reporter can compile a report on
    future projections without requiring inline citations in message content.
    """
    # Arrange
    messages: list[AnyMessage] = [HumanMessage("What is the forecast?")]
    forecasts = [{"question": "Will treaty pass?", "summary": "70% probability"}]

    # Act + Assert
    assert has_researched_material(messages, workspace_forecasts=forecasts) is True


def test_has_researched_material_finds_citations_in_tool_message_artifact() -> None:
    """Specialist tools store verified answers with markdown citations in
    ToolMessage.artifact['text']. The material check must detect these citations as researched material.
    """
    # Arrange
    messages: list[AnyMessage] = [
        ToolMessage(
            content="Summary",
            tool_call_id="call_cites",
            artifact={"text": "Verified source [1](https://example.com)."},
        ),
    ]

    # Act + Assert
    assert has_researched_material(messages) is True


def test_a_tool_message_without_an_artifact_counts_when_its_content_has_a_link() -> (
    None
):
    # Arrange
    messages: list[AnyMessage] = [
        ToolMessage(
            content="Briefing [source](https://example.com/b).",
            tool_call_id="call_1",
        )
    ]

    # Act + Assert
    assert has_researched_material(messages) is True


def test_a_tool_message_whose_artifact_has_no_link_is_not_material() -> None:
    # Arrange
    messages: list[AnyMessage] = [
        ToolMessage(
            content="Briefing [source](https://example.com/b).",
            tool_call_id="call_1",
            artifact={"text": "No sources were found."},
        )
    ]

    # Act + Assert
    assert has_researched_material(messages) is False
