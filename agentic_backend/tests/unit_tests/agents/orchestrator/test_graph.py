"""Tests for the supervisor orchestrator graph topology and execution loops."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.prebuilt.tool_node import ToolInvocationError
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agents.orchestrator import build_graph, build_runtime_config
from agents.orchestrator.state import build_initial_orchestrator_state
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE
from agents.reporter.state import OutlineDraft
from models import LLMInvocationError
from unit_tests.agents.orchestrator.conftest import ScriptedChatModel

supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")
outline_module = importlib.import_module("agents.reporter.nodes.outline")
llm_module = importlib.import_module("llm")

CITED_ANSWER = "Here is the situation [1](https://reuters.com/x)."


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


def _call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1"}])


def _script_supervisor(
    monkeypatch: pytest.MonkeyPatch, replies: list[AIMessage]
) -> None:
    fake = ScriptedChatModel(list(replies))
    monkeypatch.setattr(supervisor_module, "_build_supervisor_client", lambda: fake)


def _stub_outline(monkeypatch: pytest.MonkeyPatch, calls: list[int]) -> None:
    async def draft(*args: Any, **kwargs: Any) -> OutlineDraft:
        calls.append(1)
        return OutlineDraft(sections=["First", "Second"], notice="")

    monkeypatch.setattr(outline_module, "ainvoke_structured", draft)


def _stub_report_text(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=[text]),
    )


def _researched_report_request() -> dict[str, Any]:
    return {
        "messages": [
            HumanMessage("What happened?"),
            AIMessage(CITED_ANSWER),
            HumanMessage("Write me a report"),
        ]
    }


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


@pytest.mark.anyio
async def test_a_tool_call_that_fails_the_tool_schema_raises_instead_of_ending_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default ToolNode would turn this into an error ToolMessage nothing retries,
    so the turn would end with a footer, no answer, and no refund.
    """
    # Arrange
    _script_supervisor(monkeypatch, [_call("run_expert", query={"not": "a string"})])

    # Act + Assert
    with pytest.raises(ToolInvocationError):
        await build_graph().ainvoke(build_initial_orchestrator_state("q"))


@pytest.mark.anyio
async def test_a_pipeline_error_inside_a_tool_propagates_out_of_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _script_supervisor(monkeypatch, [_call("run_expert", query="q")])

    async def failing_expert(state: Any) -> dict[str, Any]:
        raise LLMInvocationError("Model call failed.")

    monkeypatch.setattr(
        "agents.orchestrator.tools.expert.expert_graph.ainvoke", failing_expert
    )

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await build_graph().ainvoke(build_initial_orchestrator_state("q"))


@pytest.mark.anyio
async def test_a_report_pauses_then_resumes_and_writes_without_rerunning_the_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[int] = []
    _script_supervisor(monkeypatch, [_call("run_reporter", topic="situation")])
    _stub_outline(monkeypatch, outline_calls)
    compiled = build_graph(checkpointer=InMemorySaver())
    config = _config("report-resume-1")
    await compiled.ainvoke(_researched_report_request(), config=config)
    paused = await compiled.aget_state(config)
    _stub_report_text(monkeypatch, "The report text.")

    # Act
    updates = [
        update
        async for update in compiled.astream(
            Command(resume={"action": "approve"}),
            config=config,
            stream_mode="updates",
        )
    ]
    final = await compiled.aget_state(config)

    # Assert
    assert paused.next == ("tools",)
    assert [list(update) for update in updates] == [["tools"]]
    assert final.next == ()
    assert final.values["messages"][-1].artifact == {"text": "The report text."}
    assert len(outline_calls) == 1


@pytest.mark.anyio
async def test_a_resumed_report_streams_its_text_from_the_write_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _script_supervisor(monkeypatch, [_call("run_reporter", topic="situation")])
    _stub_outline(monkeypatch, [])
    compiled = build_graph(checkpointer=InMemorySaver())
    config = _config("report-resume-2")
    await compiled.ainvoke(_researched_report_request(), config=config)
    _stub_report_text(monkeypatch, "The report text.")

    # Act
    events = [
        event
        async for event in compiled.astream(
            Command(resume={"action": "approve"}),
            config=config,
            stream_mode="messages",
            subgraphs=True,
        )
    ]
    streamed = "".join(
        event[1][0].text
        for event in events
        if event[1][1].get("langgraph_node") == "write"
    )

    # Assert
    assert streamed == "The report text."


@pytest.mark.anyio
async def test_a_new_query_on_a_paused_thread_supersedes_the_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _script_supervisor(
        monkeypatch,
        [_call("run_reporter", topic="situation"), AIMessage("assistant reply")],
    )
    _stub_outline(monkeypatch, [])
    compiled = build_graph(checkpointer=InMemorySaver())
    config = _config("report-supersede-1")
    await compiled.ainvoke(_researched_report_request(), config=config)

    # Act
    await compiled.ainvoke(
        build_initial_orchestrator_state("hello again"), config=config
    )
    state = await compiled.aget_state(config)

    # Assert
    assert state.next == ()
    assert state.interrupts == ()
    assert state.values["messages"][-1].text == "assistant reply"


@pytest.mark.anyio
async def test_a_report_with_no_material_reaches_the_custom_stream_as_a_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _script_supervisor(monkeypatch, [_call("run_reporter", topic="situation")])

    # Act
    events = [
        event
        async for event in build_graph().astream(
            build_initial_orchestrator_state("write me a report"),
            stream_mode="custom",
            subgraphs=True,
        )
    ]

    # Assert
    assert [e[1] for e in events] == [{"type": "notice", "text": NO_MATERIAL_NOTICE}]


@pytest.mark.anyio
async def test_a_cancelled_report_reaches_the_custom_stream_as_one_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _script_supervisor(monkeypatch, [_call("run_reporter", topic="situation")])
    _stub_outline(monkeypatch, [])
    compiled = build_graph(checkpointer=InMemorySaver())
    config = _config("report-cancel-1")
    await compiled.ainvoke(_researched_report_request(), config=config)

    # Act
    events = [
        event
        async for event in compiled.astream(
            Command(resume={"action": "cancel"}),
            config=config,
            stream_mode="custom",
            subgraphs=True,
        )
    ]

    # Assert
    notices = [e[1] for e in events if e[1].get("type") == "notice"]
    assert notices == [{"type": "notice", "text": CANCELLED_NOTICE}]
