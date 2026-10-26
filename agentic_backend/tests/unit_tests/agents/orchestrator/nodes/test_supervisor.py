"""Tests for the two-phase supervisor orchestrator node."""

from __future__ import annotations

import importlib
from typing import Any, Optional

import pytest
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.constants import TAG_NOSTREAM

from agents.orchestrator.config import HISTORY_WINDOW_MESSAGES
from agents.orchestrator.consts.menu import (
    DYNAMIC_FOOTER_SYSTEM_PROMPT,
    STATIC_NEXT_STEPS_MENU,
)
from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT
from agents.orchestrator.state import OrchestratorState
from agents.orchestrator.tools import ALL_TOOLS
from config import FOOTER_PREFIX
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


@pytest.mark.anyio
async def test_supervisor_answers_small_talk_in_the_routing_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the user message is small talk, the one routing call already holds the answer:
    the supervisor returns it whole, with destination 'other', and calls the model once.
    """
    # Arrange
    user_message = "Good morning! Who are you?"
    expected_chat_reply = "Good morning! I am GeopoliticAI's supervisor assistant."
    state: OrchestratorState = {"messages": [HumanMessage(user_message)]}
    supervisor_fake = ScriptedChatModel(
        [AIMessage(content=f"  {expected_chat_reply}\n", tool_calls=[])]
    )
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

    # Act
    result = await supervisor(state, writer=events.append)

    # Assert
    assert result == {
        "messages": [AIMessage(expected_chat_reply)],
        "destination": "other",
    }
    assert events == []
    assert supervisor_fake.invocations == [
        [SystemMessage(SUPERVISOR_SYSTEM_PROMPT), HumanMessage(user_message)]
    ]


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
    state: OrchestratorState = {"messages": [HumanMessage(user_message)]}

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
    state: OrchestratorState = {"messages": messages}

    chat_reply = "The capital of Turkey is Ankara."
    supervisor_fake = ScriptedChatModel([AIMessage(content=chat_reply, tool_calls=[])])
    events: list[dict[str, Any]] = []

    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

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


def _orphaned_tool_result_history(replies_after: int) -> list[AnyMessage]:
    """A tool call, its result, a human turn, then `replies_after` assistant replies."""
    return [
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
        ToolMessage(content="Orphaned tool result", tool_call_id="call_orphan"),
        HumanMessage("Clean user question"),
        *[AIMessage(f"Reply {idx}") for idx in range(replies_after)],
    ]


def test_supervisor_history_window_drops_orphaned_leading_tool_message() -> None:
    """When the window starts on a ToolMessage whose AI parent was sliced out, the orphan
    guard drops it so the provider never sees a tool result without its call.
    """
    # Arrange
    # The window keeps the last HISTORY_WINDOW_MESSAGES messages, so the tool
    # result sits first in the window when the human turn and the replies after
    # it fill all but one slot.
    messages = _orphaned_tool_result_history(replies_after=HISTORY_WINDOW_MESSAGES - 2)

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    assert sanitized[0] == HumanMessage("Clean user question")
    assert len(sanitized) == HISTORY_WINDOW_MESSAGES - 1


@pytest.mark.parametrize(
    ("replies_after", "expected_first"),
    [
        pytest.param(HISTORY_WINDOW_MESSAGES - 3, "call", id="at-limit-keeps-the-pair"),
        pytest.param(
            HISTORY_WINDOW_MESSAGES - 2, "human", id="one-past-drops-the-call"
        ),
    ],
)
def test_supervisor_history_window_boundary(
    replies_after: int, expected_first: str
) -> None:
    """At the limit the tool call and result both fit; one more message pushes the call out
    and the result with it.
    """
    # Arrange
    messages = _orphaned_tool_result_history(replies_after)

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    first = sanitized[0]
    assert ("call" if isinstance(first, AIMessage) else "human") == expected_first
    assert len(sanitized) <= HISTORY_WINDOW_MESSAGES


def test_supervisor_sanitizer_does_not_cancel_a_tool_call_that_was_answered() -> None:
    """A call answered by its ToolMessage gets no synthetic cancellation beside it."""
    # Arrange
    messages: list[AnyMessage] = [
        HumanMessage("Question"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_expert",
                    "args": {"query": "q"},
                    "id": "c1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="Summary", tool_call_id="c1", artifact={"text": "Full"}),
        HumanMessage("Follow-up"),
    ]

    # Act
    sanitized = _sanitize_and_slice_messages(messages)

    # Assert
    assert [type(m).__name__ for m in sanitized] == [
        "HumanMessage",
        "AIMessage",
        "ToolMessage",
        "HumanMessage",
    ]
    assert sanitized[2].content == "Full"


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
    state: OrchestratorState = {
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
        "- Explore in depth with the deep research agent (4 research turns)\n"
        "- Generate a Delphi forecast (8 research turns)\n"
        "- Generate a comprehensive report (1 research turn)"
    )
    expected_notice_chunk = (
        "\n\n---\n"
        "**What next?**\n"
        "- Ask about NATO enhanced Forward Presence in Estonia (0 research turns)\n"
        "- Explore in depth with the deep research agent (4 research turns)\n"
        "- Generate a Delphi forecast (8 research turns)\n"
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
async def test_supervisor_pass_two_falls_back_to_static_menu_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the dynamic footer model call raises an exception, Pass 2 must fall back to
    STATIC_NEXT_STEPS_MENU, emit it as a notice, and return an AIMessage.
    """
    # Arrange
    state: OrchestratorState = {
        "messages": [
            ToolMessage(
                content="Research summary.",
                tool_call_id="call_fail",
            ),
        ]
    }

    expected_static_chunk = f"{FOOTER_PREFIX}{STATIC_NEXT_STEPS_MENU}"

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
async def test_supervisor_rejects_an_empty_chat_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the supervisor returns neither tool calls nor text, it must raise
    LLMInvocationError rather than returning an empty message.
    """
    # Arrange
    state: OrchestratorState = {"messages": [HumanMessage("Hello?")]}
    supervisor_fake = ScriptedChatModel([AIMessage(content="  ", tool_calls=[])])
    monkeypatch.setattr(
        node_module, "_build_supervisor_client", lambda: supervisor_fake
    )

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model returned an empty answer."):
        await supervisor(state, writer=lambda _: None)


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
    state: OrchestratorState = {"messages": [HumanMessage("Sample query")]}
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
async def test_supervisor_keeps_only_the_first_of_two_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    first = {
        "name": "run_expert",
        "args": {"query": "a"},
        "id": "c1",
        "type": "tool_call",
    }
    second = {
        "name": "run_deep_expert",
        "args": {"query": "b"},
        "id": "c2",
        "type": "tool_call",
    }
    fake = ScriptedChatModel([AIMessage(content="", tool_calls=[first, second])])
    monkeypatch.setattr(node_module, "_build_supervisor_client", lambda: fake)

    # Act
    result = await supervisor(
        {"messages": [HumanMessage("Question")]}, writer=lambda _: None
    )

    # Assert
    assert result["messages"] == [AIMessage(content="", tool_calls=[first])]
    assert result["destination"] == "geopolitical"


def test_tool_destination_map_covers_exactly_the_bound_tools() -> None:
    # Act
    mapped = set(TOOL_DESTINATION_MAP)

    # Assert
    assert mapped == {t.name for t in ALL_TOOLS}


@pytest.mark.anyio
async def test_supervisor_rejects_an_unknown_tool_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    call = {
        "name": "run_unknown",
        "args": {"query": "q"},
        "id": "c1",
        "type": "tool_call",
    }
    fake = ScriptedChatModel([AIMessage(content="", tool_calls=[call])])
    monkeypatch.setattr(node_module, "_build_supervisor_client", lambda: fake)

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="unknown tool"):
        await supervisor({"messages": [HumanMessage("Q")]}, writer=lambda _: None)


@pytest.mark.anyio
async def test_supervisor_rejects_a_tool_call_with_a_blank_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    call = {
        "name": "run_expert",
        "args": {"query": "  "},
        "id": "c1",
        "type": "tool_call",
    }
    fake = ScriptedChatModel([AIMessage(content="", tool_calls=[call])])
    monkeypatch.setattr(node_module, "_build_supervisor_client", lambda: fake)

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="no query"):
        await supervisor({"messages": [HumanMessage("Q")]}, writer=lambda _: None)


@pytest.mark.anyio
async def test_supervisor_rejects_a_tool_call_the_model_could_not_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    reply = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "run_expert",
                "args": "{not json",
                "id": "c1",
                "error": "bad args",
                "type": "invalid_tool_call",
            }
        ],
    )
    fake = ScriptedChatModel([reply])
    monkeypatch.setattr(node_module, "_build_supervisor_client", lambda: fake)

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="could not parse"):
        await supervisor({"messages": [HumanMessage("Q")]}, writer=lambda _: None)


@pytest.mark.anyio
async def test_supervisor_turns_a_provider_failure_into_an_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    fake = ScriptedChatModel([TimeoutError("provider timed out")])
    monkeypatch.setattr(node_module, "_build_supervisor_client", lambda: fake)

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model call failed."):
        await supervisor({"messages": [HumanMessage("Q")]}, writer=lambda _: None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content", "expected_body"),
    [
        pytest.param("", STATIC_NEXT_STEPS_MENU, id="empty"),
        pytest.param("  \n ", STATIC_NEXT_STEPS_MENU, id="whitespace"),
        pytest.param([], STATIC_NEXT_STEPS_MENU, id="empty-block-list"),
        pytest.param(
            "  **What next?**\n- Ask  \n", "**What next?**\n- Ask", id="padded"
        ),
    ],
)
async def test_supervisor_footer_uses_the_static_menu_only_when_the_reply_is_blank(
    monkeypatch: pytest.MonkeyPatch,
    content: Any,
    expected_body: str,
) -> None:
    # Arrange
    state: OrchestratorState = {
        "messages": [ToolMessage(content="Summary.", tool_call_id="c1")]
    }
    fake = ScriptedChatModel([AIMessage(content=content)])
    monkeypatch.setattr(node_module, "_build_footer_client", lambda: fake)

    # Act
    result = await supervisor(state, writer=lambda _: None)

    # Assert
    assert result == {"messages": [AIMessage(f"{FOOTER_PREFIX}{expected_body}")]}


class RecordingChatModel:
    """Records how the supervisor's builders configure the model they get."""

    def __init__(self) -> None:
        self.bound_tools: list[Any] = []
        self.bind_kwargs: dict[str, Any] = {}
        self.config_kwargs: dict[str, Any] = {}

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> RecordingChatModel:
        self.bound_tools = tools
        self.bind_kwargs = kwargs
        return self

    def with_config(self, **kwargs: Any) -> RecordingChatModel:
        self.config_kwargs = kwargs
        return self


def test_supervisor_client_binds_every_tool_one_at_a_time_and_is_not_streamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    recorder = RecordingChatModel()
    monkeypatch.setattr(node_module, "build_chat_model", lambda settings: recorder)

    # Act
    node_module._build_supervisor_client()

    # Assert
    assert recorder.bound_tools == ALL_TOOLS
    assert recorder.bind_kwargs == {"parallel_tool_calls": False}
    assert recorder.config_kwargs == {"tags": [TAG_NOSTREAM]}


def test_footer_client_is_not_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    recorder = RecordingChatModel()
    monkeypatch.setattr(node_module, "build_chat_model", lambda settings: recorder)

    # Act
    node_module._build_footer_client()

    # Assert
    assert recorder.bound_tools == []
    assert recorder.config_kwargs == {"tags": [TAG_NOSTREAM]}
