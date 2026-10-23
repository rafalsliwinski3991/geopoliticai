"""Tests for the supervisor orchestrator graph topology and execution loops."""

from __future__ import annotations

import importlib
from typing import Any, Optional

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.store.memory import InMemoryStore

from agents.orchestrator import build_graph, build_runtime_config
from agents.orchestrator.state import build_initial_orchestrator_state

supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")


class ScriptedChatModel:
    """Scripted chat model returning pre-programmed responses in order."""

    def __init__(self, responses: list[AnyMessage]) -> None:
        self.responses = list(responses)

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
        if not self.responses:
            raise AssertionError("ScriptedChatModel exhausted")
        return self.responses.pop(0)


def test_graph_has_supervisor_and_tools_nodes() -> None:
    """The multi-agent orchestrator topology consists only of the supervisor and tools nodes."""
    # Act
    nodes = set(build_graph().get_graph().nodes)

    # Assert
    assert nodes - {"__start__", "__end__"} == {"supervisor", "tools"}


def test_graph_has_expected_edges() -> None:
    """The graph routes from START to supervisor, conditionally to tools or END, and tools conditionally back."""
    # Act
    edges = {(edge.source, edge.target) for edge in build_graph().get_graph().edges}

    # Assert
    assert {
        (START, "supervisor"),
        ("supervisor", "tools"),
        ("supervisor", END),
        ("tools", "supervisor"),
        ("tools", END),
    } <= edges


def test_build_graph_needs_no_checkpointer() -> None:
    """Constructing the graph needs no checkpointer for offline compilation."""
    # Act + Assert
    assert build_graph() is not None


def test_build_graph_compiles_with_the_store() -> None:
    """The store passed to build_graph is bound to the compiled graph instance."""
    # Arrange
    store = InMemoryStore()

    # Act
    graph = build_graph(store=store)

    # Assert
    assert graph.store is store


@pytest.mark.anyio
async def test_graph_executes_supervisor_tool_supervisor_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A specialist research tool execution loops back to supervisor for post-tool dynamic footer synthesis."""
    # Arrange
    TOOL_NAME = "run_expert"
    CALL_ID = "call-expert-1"
    TOOL_QUERY = "What is happening in Sudan?"
    FOOTER_TEXT = "\n\n---\n1. Deep dive\n2. Forecast"

    supervisor_response = AIMessage(
        content="",
        tool_calls=[{"name": TOOL_NAME, "args": {"query": TOOL_QUERY}, "id": CALL_ID}],
    )
    footer_response = AIMessage(content="1. Deep dive\n2. Forecast")

    monkeypatch.setattr(
        supervisor_module,
        "_build_supervisor_client",
        lambda: ScriptedChatModel([supervisor_response]),
    )
    monkeypatch.setattr(
        supervisor_module,
        "_build_footer_client",
        lambda: ScriptedChatModel([footer_response]),
    )

    async def fake_expert_ainvoke(state: Any) -> dict[str, Any]:
        return {
            "answer": "Verified Sudan analysis [1](https://reuters.com/sudan).",
            "sources": [],
        }

    monkeypatch.setattr(
        "agents.orchestrator.tools.expert.expert_graph.ainvoke", fake_expert_ainvoke
    )

    compiled = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id="t-loop-1")
    initial_state = build_initial_orchestrator_state(TOOL_QUERY)

    # Act
    updates = [
        data
        async for data in compiled.astream(
            initial_state, config=config, stream_mode="updates"
        )
    ]
    final_state = await compiled.aget_state(config)

    # Assert
    executed_nodes = [list(up.keys())[0] for up in updates]
    assert executed_nodes == ["supervisor", "tools", "supervisor"]
    assert final_state.next == ()
    messages = final_state.values["messages"]
    assert len(messages) == 4
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage) and bool(messages[1].tool_calls)
    assert isinstance(messages[2], ToolMessage)
    assert isinstance(messages[3], AIMessage) and not messages[3].tool_calls
    assert messages[3].text == FOOTER_TEXT


@pytest.mark.anyio
async def test_graph_routes_reporter_tool_straight_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reporter tool execution skips supervisor pass 2 and routes straight to END."""
    # Arrange
    TOOL_NAME = "run_reporter"
    CALL_ID = "call-rep-1"
    TOPIC = "Sudan crisis report"

    supervisor_response = AIMessage(
        content="",
        tool_calls=[{"name": TOOL_NAME, "args": {"topic": TOPIC}, "id": CALL_ID}],
    )

    monkeypatch.setattr(
        supervisor_module,
        "_build_supervisor_client",
        lambda: ScriptedChatModel([supervisor_response]),
    )

    compiled = build_graph(checkpointer=InMemorySaver())
    config = build_runtime_config(thread_id="t-rep-1")
    initial_state = build_initial_orchestrator_state("Write a report on Sudan")

    # Act
    updates = [
        data
        async for data in compiled.astream(
            initial_state, config=config, stream_mode="updates"
        )
    ]
    final_state = await compiled.aget_state(config)

    # Assert
    executed_nodes = [list(up.keys())[0] for up in updates]
    assert executed_nodes == ["supervisor", "tools"]
    assert final_state.next == ()
    assert final_state.values.get("destination") == "report"
    messages = final_state.values["messages"]
    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage) and bool(messages[1].tool_calls)
    assert isinstance(messages[2], ToolMessage)
