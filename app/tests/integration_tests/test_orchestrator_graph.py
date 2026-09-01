import importlib
from typing import Any, AsyncIterator, cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START

from agents.orchestrator.state import (
    Destination,
    RouteDecision,
    build_initial_orchestrator_state,
)
from models import Candidate, Source

orchestrator = importlib.import_module("agents.orchestrator")
graph_module = importlib.import_module("agents.orchestrator.graph")
classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
chat_module = importlib.import_module("agents.orchestrator.nodes.chat")
retrieve_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
llm_module = importlib.import_module("llm")


def test_graph_has_exactly_three_nodes() -> None:
    nodes = set(orchestrator.build_graph().get_graph().nodes)

    assert nodes - {"__start__", "__end__"} == {"classify", "expert", "chat"}


def test_graph_forks_after_classify() -> None:
    edges = {
        (edge.source, edge.target)
        for edge in orchestrator.build_graph().get_graph().edges
    }

    assert {
        (START, "classify"),
        ("classify", "expert"),
        ("classify", "chat"),
        ("expert", END),
        ("chat", END),
    } <= edges


def test_build_graph_needs_no_checkpointer() -> None:
    assert orchestrator.build_graph() is not None


async def _geopolitical_candidates(query: str, policy: Any) -> list[Candidate]:
    return [Candidate("title", "https://reuters.com/x", "reuters.com")]


async def _geopolitical_sources(
    candidates: list[Candidate], policy: Any
) -> list[Source]:
    return [Source("title", "https://reuters.com/x", "body")]


def _route(monkeypatch: pytest.MonkeyPatch, destination: str) -> None:
    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        return RouteDecision(
            destination=cast(Destination, destination), standalone_query="rewritten"
        )

    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)


@pytest.mark.anyio
async def test_expert_branch_streams_namespaced_answer_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )

    events = [
        event
        async for event in orchestrator.build_graph().astream(
            build_initial_orchestrator_state("question"),
            stream_mode="messages",
            subgraphs=True,
        )
    ]
    answer_events = [
        event for event in events if event[1][1].get("langgraph_node") == "answer"
    ]

    assert answer_events
    assert all(event[0] for event in answer_events)
    assert "".join(event[1][0].text() for event in answer_events) == "Hello world."


@pytest.mark.anyio
async def test_expert_branch_streams_nothing_without_subgraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )

    events = [
        event
        async for event in orchestrator.build_graph().astream(
            build_initial_orchestrator_state("question"), stream_mode="messages"
        )
    ]

    answer_events = [
        event for event in events if event[1].get("langgraph_node") == "answer"
    ]
    assert answer_events == []


@pytest.mark.anyio
async def test_classifier_tokens_never_reach_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route(monkeypatch, "other")

    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield "chat answer"

    monkeypatch.setattr(chat_module, "astream_messages", stream)
    events = [
        event
        async for event in orchestrator.build_graph().astream(
            build_initial_orchestrator_state("hello"), stream_mode="messages"
        )
    ]

    assert all(event[1].get("langgraph_node") != "classify" for event in events)


@pytest.mark.anyio
async def test_chat_branch_never_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_search(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("chat branch must not search")

    monkeypatch.setattr(retrieve_module, "search_allowlisted", forbidden_search)
    _route(monkeypatch, "other")

    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield "chat answer"

    monkeypatch.setattr(chat_module, "astream_messages", stream)
    events = [
        event
        async for event in orchestrator.build_graph().astream(
            build_initial_orchestrator_state("hello"), stream_mode="messages"
        )
    ]

    assert any(event[1].get("langgraph_node") == "chat" for event in events)


@pytest.mark.anyio
async def test_thread_carries_history_between_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[list[Any]] = []

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> RouteDecision:
        received.append(list(messages))
        return RouteDecision(destination="other", standalone_query="rewritten")

    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield "assistant reply"

    monkeypatch.setattr(classify_module, "ainvoke_structured", decide)
    monkeypatch.setattr(chat_module, "astream_messages", stream)
    compiled = orchestrator.build_graph(checkpointer=InMemorySaver())
    config = orchestrator.build_runtime_config(thread_id="thread-1")

    await compiled.ainvoke(
        build_initial_orchestrator_state("first question"), config=config
    )
    await compiled.ainvoke(
        build_initial_orchestrator_state("second question"), config=config
    )

    assert len(received) == 2
    assert [message.content for message in received[1]] == [
        "first question",
        "assistant reply",
        "second question",
    ]
