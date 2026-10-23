"""Tests for the two-phase supervisor orchestrator node."""

from __future__ import annotations

import importlib
from typing import Any, AsyncIterator, Optional

import pytest
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from agents.orchestrator.consts.menu import DYNAMIC_FOOTER_SYSTEM_PROMPT
from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT
from agents.orchestrator.state import GeopoliticState
from models import LLMInvocationError

node_module = importlib.import_module("agents.orchestrator.nodes.supervisor")
TOOL_DESTINATION_MAP = node_module.TOOL_DESTINATION_MAP
_sanitize_and_slice_messages = node_module._sanitize_and_slice_messages
supervisor = node_module.supervisor


class ScriptedChatModel:
    """Scripted model returning pre-programmed responses in order and recording invocations."""

    def __init__(self, responses: list[AnyMessage | Exception]) -> None:
        self.responses = list(responses)
        self.invocations: list[list[AnyMessage]] = []

    def bind_tools(self, *args: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def with_config(self, *args: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    async def ainvoke(
        self,
        messages: list[AnyMessage],
        *,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AnyMessage:
        self.invocations.append(messages)
        if not self.responses:
            raise AssertionError(
                "ScriptedChatModel exhausted: unexpected model invocation"
            )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ScriptedStreamer:
    """Scripted stream returning chunks for astream_messages."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = list(chunks)
        self.invocations: list[dict[str, Any]] = []

    async def __call__(
        self,
        system_prompt: str,
        messages: list[AnyMessage],
        *,
        config: Optional[RunnableConfig] = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        self.invocations.append({"prompt": system_prompt, "messages": list(messages)})
        for chunk in self.chunks:
            yield chunk


@pytest.mark.anyio
async def test_supervisor_answers_small_talk_directly_without_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user message is conversational small talk, the supervisor must stream the
    answer directly without tool calls, and route to destination 'other'.
    """
    # Arrange
    user_message = "Good morning! Who are you?"
    expected_chat_reply = "Good morning! I am GeopoliticAI's supervisor assistant."
    state: GeopoliticState = {"messages": [HumanMessage(user_message)]}

    supervisor_fake = ScriptedChatModel(
        [AIMessage(content=expected_chat_reply, tool_calls=[])]
    )
    streamer_fake = ScriptedStreamer(
        ["Good morning! ", "I am GeopoliticAI's ", "supervisor assistant."]
    )
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )
    monkeypatch.setattr(node_module, "astream_messages", streamer_fake)

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result == {
        "messages": [
            AIMessage("Good morning! I am GeopoliticAI's supervisor assistant.")
        ],
        "destination": "other",
    }
    assert events == []
    assert len(streamer_fake.invocations) == 1
    assert streamer_fake.invocations[0]["prompt"] == SUPERVISOR_SYSTEM_PROMPT
    assert streamer_fake.invocations[0]["messages"] == [HumanMessage(user_message)]


@pytest.mark.anyio
async def test_supervisor_picks_expert_tool_with_rewritten_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user asks a factual geopolitical question, the supervisor must invoke run_expert
    with a standalone rewritten query and route to destination 'geopolitical'.
    """
    # Arrange
    user_message = "What is the Montreux Convention?"
    rewritten_query = "What are the rules and background of the 1936 Montreux Convention regarding the Turkish Straits?"
    state: GeopoliticState = {"messages": [HumanMessage(user_message)]}

    expected_tool_call = {
        "name": "run_expert",
        "args": {"query": rewritten_query},
        "id": "call_expert_987",
        "type": "tool_call",
    }
    supervisor_fake = ScriptedChatModel(
        [
            AIMessage(
                content="Preamble that should be suppressed",
                tool_calls=[expected_tool_call],
            )
        ]
    )
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result == {
        "messages": [AIMessage(content="", tool_calls=[expected_tool_call])],
        "destination": "geopolitical",
    }
    assert events == []
    assert len(supervisor_fake.invocations) == 1
    payload = supervisor_fake.invocations[0]
    assert len(payload) == 2
    assert payload[0] == SystemMessage(SUPERVISOR_SYSTEM_PROMPT)
    assert payload[1] == HumanMessage(user_message)


@pytest.mark.anyio
async def test_supervisor_sanitizes_unanswered_tool_calls_with_synthetic_tool_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When prior turns contain unfulfilled tool calls (e.g. from user cancellation),
    the sanitizer must inject synthetic cancellation ToolMessages before subsequent human turns.
    """
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Analyze Black Sea grain initiative"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": "Black Sea grain initiative status"},
                    "id": "call_expert_cancelled_1",
                    "type": "tool_call",
                }
            ],
        ),
        HumanMessage("Wait, stop that. What is the capital of Turkey?"),
    ]
    state: GeopoliticState = {"messages": messages}

    chat_reply = "The capital of Turkey is Ankara."
    supervisor_fake = ScriptedChatModel([AIMessage(content=chat_reply, tool_calls=[])])
    streamer_fake = ScriptedStreamer([chat_reply])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )
    monkeypatch.setattr(node_module, "astream_messages", streamer_fake)

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result == {
        "messages": [AIMessage("The capital of Turkey is Ankara.")],
        "destination": "other",
    }
    assert len(supervisor_fake.invocations) == 1
    payload = supervisor_fake.invocations[0]
    # Check that a synthetic cancellation ToolMessage was injected between the AIMessage and the second HumanMessage
    assert len(payload) == 5
    assert payload[0] == SystemMessage(SUPERVISOR_SYSTEM_PROMPT)
    assert payload[1] == HumanMessage("Analyze Black Sea grain initiative")
    assert isinstance(payload[2], AIMessage)
    assert payload[2].tool_calls[0]["id"] == "call_expert_cancelled_1"
    synthetic_msg = payload[3]
    assert isinstance(synthetic_msg, ToolMessage)
    assert synthetic_msg.content == "Tool execution for run_expert was cancelled."
    assert synthetic_msg.tool_call_id == "call_expert_cancelled_1"
    assert payload[4] == HumanMessage("Wait, stop that. What is the capital of Turkey?")


def test_supervisor_history_window_drops_orphaned_leading_tool_message() -> None:
    """When history window slicing begins on a ToolMessage mid-turn, the orphan guard must
    drop leading ToolMessages until reaching a HumanMessage or AIMessage to avoid API protocol errors.
    """
    # Arrange
    # Build 25 messages.
    # We want message at index -20 (index 5) to be a ToolMessage whose parent AIMessage was sliced out.
    messages: list[AnyMessage] = [
        HumanMessage("Early turn 0"),
        AIMessage("Early reply 0"),
        HumanMessage("Early turn 1"),
        AIMessage("Early reply 1"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {},
                    "id": "call_orphan",
                    "type": "tool_call",
                }
            ],
        ),
        # Index 5 in raw history (which will be index 0 of the 20-message slice):
        ToolMessage(content="Orphaned tool result", tool_call_id="call_orphan"),
        # Index 6:
        HumanMessage("Clean user question"),
    ]
    # Add 18 more messages so total is 25:
    for idx in range(18):
        messages.append(AIMessage(f"Reply {idx}"))

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    # Without the orphan guard, sanitized[0] would be the ToolMessage at index 5.
    # With the guard, that orphaned ToolMessage is dropped, and sanitized starts with HumanMessage("Clean user question").
    assert not isinstance(sanitized[0], ToolMessage)
    assert sanitized[0] == HumanMessage("Clean user question")


@pytest.mark.anyio
async def test_supervisor_pass_two_generates_dynamic_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the last message is a ToolMessage, Pass 2 must invoke the footer model, emit the
    formatted notice chunk, and return an AIMessage with the dynamic footer.
    """
    # Arrange
    tool_summary = (
        "Synthesized verified research on 'Baltic defense posture' from 3 sources."
    )
    state: GeopoliticState = {
        "messages": [
            HumanMessage("What is the Baltic defense posture?"),
            ToolMessage(
                content=tool_summary,
                tool_call_id="call_expert_pass2",
                artifact={"text": "Detailed defense analysis."},
            ),
        ]
    }

    dynamic_footer_text = (
        "**What next?**\n"
        "- Ask about NATO enhanced Forward Presence in Estonia (0 research turns)\n"
        "- Explore in depth with the deep research agent (10 research turns)\n"
        "- Generate a Delphi forecast (20 research turns)\n"
        "- Generate a comprehensive report (1 research turn)"
    )
    expected_notice_chunk = (
        "\n\n---\n"
        "**What next?**\n"
        "- Ask about NATO enhanced Forward Presence in Estonia (0 research turns)\n"
        "- Explore in depth with the deep research agent (10 research turns)\n"
        "- Generate a Delphi forecast (20 research turns)\n"
        "- Generate a comprehensive report (1 research turn)"
    )

    footer_fake = ScriptedChatModel([AIMessage(content=dynamic_footer_text)])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(node_module, "_build_footer_client", lambda: footer_fake)

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert events == [{"type": "notice", "text": expected_notice_chunk}]
    assert result == {"messages": [AIMessage(expected_notice_chunk)]}
    assert len(footer_fake.invocations) == 1
    prompt = footer_fake.invocations[0]
    assert prompt[0] == SystemMessage(DYNAMIC_FOOTER_SYSTEM_PROMPT)
    assert prompt[1] == HumanMessage(f"Recent tool result summary: {tool_summary}")


@pytest.mark.anyio
async def test_supervisor_pass_two_falls_back_to_static_menu_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the dynamic footer model call raises an exception, Pass 2 must fall back to
    STATIC_NEXT_STEPS_MENU, emit it as a notice, and return an AIMessage.
    """
    # Arrange
    state: GeopoliticState = {
        "messages": [
            ToolMessage(
                content="Research summary.",
                tool_call_id="call_fail",
            ),
        ]
    }

    expected_static_chunk = (
        "\n\n---\n"
        "**What next?**\n"
        "- Ask a follow-up (0 research turns)\n"
        "- Explore in depth with the deep research agent (10 research turns)\n"
        "- Generate a Delphi forecast (20 research turns)\n"
        "- Generate a comprehensive report (1 research turn)"
    )

    failing_fake = ScriptedChatModel([RuntimeError("OpenAI API rate limit exceeded")])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(node_module, "_build_footer_client", lambda: failing_fake)

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert events == [{"type": "notice", "text": expected_static_chunk}]
    assert result == {"messages": [AIMessage(expected_static_chunk)]}


def test_sanitize_and_slice_messages_replaces_tool_message_content_with_artifact_text() -> (
    None
):
    """In prompt view, ToolMessage.content is replaced with artifact['text'] so the supervisor
    has access to full verified research rather than truncated tool summaries.
    """
    # Arrange
    short_summary = "Synthesized verified research on 'Taiwan Strait' from 2 sources."
    full_artifact_text = "Comprehensive briefing on Taiwan Strait maritime security [1](https://example.com/taiwan)."
    messages: list[AnyMessage] = [
        HumanMessage("What is the situation in Taiwan Strait?"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": "Taiwan Strait"},
                    "id": "call_tw",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content=short_summary,
            tool_call_id="call_tw",
            artifact={"text": full_artifact_text},
        ),
    ]

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    tool_msg = sanitized[2]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.content == full_artifact_text
    assert tool_msg.artifact == {"text": full_artifact_text}


@pytest.mark.anyio
async def test_supervisor_rejects_empty_chat_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the supervisor produces neither tool calls nor any streamable chat tokens,
    it must raise LLMInvocationError rather than returning an empty message.
    """
    # Arrange
    state: GeopoliticState = {"messages": [HumanMessage("Hello?")]}
    supervisor_fake = ScriptedChatModel([AIMessage(content="", tool_calls=[])])
    empty_streamer = ScriptedStreamer([])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )
    monkeypatch.setattr(node_module, "astream_messages", empty_streamer)

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model returned an empty answer."):
        await supervisor(state, writer=events.append)


@pytest.mark.parametrize(
    ("tool_name", "expected_destination"),
    [
        ("run_expert", "geopolitical"),
        ("run_deep_expert", "deep"),
        ("run_deep_forecaster", "forecast"),
        ("run_reporter", "report"),
    ],
)
@pytest.mark.anyio
async def test_supervisor_maps_all_specialist_tools_to_destinations(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    expected_destination: str,
) -> None:
    """Every specialist tool in TOOL_DESTINATION_MAP must route to its assigned destination."""
    # Arrange
    tool_call = {
        "name": tool_name,
        "args": {"query": "sample query"},
        "id": f"call_{tool_name}",
        "type": "tool_call",
    }
    state: GeopoliticState = {"messages": [HumanMessage("Sample query")]}
    supervisor_fake = ScriptedChatModel([AIMessage(content="", tool_calls=[tool_call])])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result["destination"] == expected_destination
    assert result["messages"] == [AIMessage(content="", tool_calls=[tool_call])]


def test_supervisor_sanitizes_unanswered_tool_calls_at_end_of_history() -> None:
    """When a thread ends with unfulfilled tool calls, synthetic cancellations must be appended
    to close the dangling tool calls cleanly.
    """
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Initial turn"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": "NATO"},
                    "id": "call_end_dangling",
                    "type": "tool_call",
                }
            ],
        ),
    ]

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    assert len(sanitized) == 3
    assert sanitized[0] == HumanMessage("Initial turn")
    assert isinstance(sanitized[1], AIMessage)
    synthetic_msg = sanitized[2]
    assert isinstance(synthetic_msg, ToolMessage)
    assert synthetic_msg.content == "Tool execution for run_expert was cancelled."
    assert synthetic_msg.tool_call_id == "call_end_dangling"


@pytest.mark.anyio
async def test_supervisor_routes_same_topic_follow_up_to_deep_expert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When following up on an earlier deep research turn on the same topic, the supervisor must
    dispatch run_deep_expert and route to destination 'deep'.
    """
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Deep research the defense posture of Germany"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_deep_expert",
                    "args": {"query": "Germany defense posture"},
                    "id": "call_deep_1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content="Detailed synthesis on German defense posture",
            tool_call_id="call_deep_1",
            artifact={"text": "German defense analysis [1](https://example.com/ger)."},
        ),
        AIMessage("\n\n---\n**What next?**\n- Ask a follow-up (0 research turns)"),
        HumanMessage("and Poland?"),
    ]
    state: GeopoliticState = {"messages": messages}

    expected_tool_call = {
        "name": "run_deep_expert",
        "args": {"query": "Poland defense posture"},
        "id": "call_deep_2",
        "type": "tool_call",
    }
    supervisor_fake = ScriptedChatModel(
        [AIMessage(content="", tool_calls=[expected_tool_call])]
    )
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result == {
        "messages": [AIMessage(content="", tool_calls=[expected_tool_call])],
        "destination": "deep",
    }
    assert events == []
    assert len(supervisor_fake.invocations) == 1
    payload = supervisor_fake.invocations[0]
    assert payload[0] == SystemMessage(SUPERVISOR_SYSTEM_PROMPT)
    assert "Follow-ups to deep research stay deep" in SUPERVISOR_SYSTEM_PROMPT
    assert payload[-1] == HumanMessage("and Poland?")
