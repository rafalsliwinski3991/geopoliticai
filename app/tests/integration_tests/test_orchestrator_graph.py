import importlib
from typing import Any, AsyncIterator, cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.types import Command

from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.orchestrator.state import (
    Destination,
    RouteDecision,
    build_initial_orchestrator_state,
)
from agents.reporter.consts.messages import NO_MATERIAL_NOTICE
from agents.reporter.consts.progress import OUTLINE_PROGRESS, REPORT_PROGRESS
from agents.reporter.state import OutlineDraft
from models import Candidate, Source

orchestrator = importlib.import_module("agents.orchestrator")
graph_module = importlib.import_module("agents.orchestrator.graph")
classify_module = importlib.import_module("agents.orchestrator.nodes.classify")
chat_module = importlib.import_module("agents.orchestrator.nodes.chat")
outline_module = importlib.import_module("agents.reporter.nodes.outline")
retrieve_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
llm_module = importlib.import_module("llm")

CITED_ANSWER = "Here is the situation [1](https://reuters.com/x)."


def test_graph_has_exactly_four_nodes() -> None:
    nodes = set(orchestrator.build_graph().get_graph().nodes)

    assert nodes - {"__start__", "__end__"} == {
        "classify",
        "expert",
        "chat",
        "reporter",
    }


def test_graph_forks_after_classify() -> None:
    edges = {
        (edge.source, edge.target)
        for edge in orchestrator.build_graph().get_graph().edges
    }

    assert {
        (START, "classify"),
        ("classify", "expert"),
        ("classify", "chat"),
        ("classify", "reporter"),
        ("expert", END),
        ("chat", END),
        ("reporter", END),
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


def _stub_outline_model(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]], sections: list[str]
) -> None:
    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> OutlineDraft:
        calls.append(list(sections))
        return OutlineDraft(sections=list(sections), notice="")

    monkeypatch.setattr(outline_module, "ainvoke_structured", decide)


def _stub_report_client(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=[text]),
    )


def _compiled() -> Any:
    return orchestrator.build_graph(checkpointer=InMemorySaver())


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


async def _seed_researched_turn(
    compiled: Any, monkeypatch: pytest.MonkeyPatch, config: dict[str, dict[str, str]]
) -> None:
    """Run one geopolitical turn so the thread holds a cited assistant answer."""
    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    _stub_report_client(monkeypatch, CITED_ANSWER)
    await compiled.ainvoke(build_initial_orchestrator_state("question"), config=config)


@pytest.mark.anyio
async def test_expert_branch_streams_namespaced_answer_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    _stub_report_client(monkeypatch, "Hello world.")

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
    _stub_report_client(monkeypatch, "Hello world.")

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


@pytest.mark.anyio
async def test_report_branch_never_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_search(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("report branch must not search")

    monkeypatch.setattr(retrieve_module, "search_allowlisted", forbidden_search)
    outline_calls: list[list[str]] = []
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First"])
    compiled = _compiled()
    config = _config("report-nosearch-1")

    # The thread already holds a cited assistant answer; the report turn runs
    # without touching the search.
    await compiled.ainvoke(
        {"messages": [AIMessage(CITED_ANSWER), HumanMessage("write me a report")]},
        config=config,
    )
    state = compiled.get_state(config=config)

    assert state.next == ("reporter",)
    assert outline_calls == [["First"]]


@pytest.mark.anyio
async def test_report_branch_pauses_at_top_level_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    compiled = _compiled()
    config = _config("report-pause-ns-1")
    await _seed_researched_turn(compiled, monkeypatch, config)
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First", "Second"])

    events = [
        event
        async for event in compiled.astream(
            build_initial_orchestrator_state("write me a report"),
            config=config,
            stream_mode=["updates"],
            subgraphs=True,
        )
    ]
    interrupts = [
        event for event in events if event[0] == () and "__interrupt__" in event[2]
    ]

    assert len(interrupts) == 1


@pytest.mark.anyio
async def test_report_progress_arrives_under_the_child_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = _compiled()
    config = _config("report-custom-ns-1")

    async def collect(input_: Any) -> list[Any]:
        return [
            event
            async for event in compiled.astream(
                input_, config=config, stream_mode=["custom"], subgraphs=True
            )
        ]

    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    _stub_report_client(monkeypatch, CITED_ANSWER)
    seed_events = await collect(build_initial_orchestrator_state("question"))

    outline_calls: list[list[str]] = []
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First"])
    report_events = await collect(build_initial_orchestrator_state("write me a report"))

    search_events = [event for event in seed_events if event[2] == SEARCH_PROGRESS]
    outline_events = [event for event in report_events if event[2] == OUTLINE_PROGRESS]

    # Reusing the `updates` namespace filter on the custom branch would drop
    # every child progress frame silently; this is the guard for that.
    assert search_events and search_events[0][0] == ()
    assert outline_events and outline_events[0][0] != ()


@pytest.mark.anyio
async def test_every_writer_node_actually_emits_through_the_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def collect(
        graph: Any, input_: Any, config: dict[str, dict[str, str]] | None = None
    ) -> list[Any]:
        return [
            event
            async for event in graph.astream(
                input_, config=config, stream_mode=["custom"], subgraphs=True
            )
        ]

    monkeypatch.setattr(retrieve_module, "search_allowlisted", _geopolitical_candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", _geopolitical_sources)
    _route(monkeypatch, "geopolitical")
    _stub_report_client(monkeypatch, "Hello world.")
    expert_events = await collect(
        orchestrator.build_graph(), build_initial_orchestrator_state("question")
    )
    assert any(event[2] == SEARCH_PROGRESS for event in expert_events)

    outline_calls: list[list[str]] = []
    compiled = _compiled()
    config = _config("report-writers-1")
    await _seed_researched_turn(compiled, monkeypatch, config)
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First", "Second"])
    pause_events = await collect(
        compiled, build_initial_orchestrator_state("write me a report"), config
    )
    assert any(event[2] == OUTLINE_PROGRESS for event in pause_events)
    resume_events = await collect(
        compiled, Command(resume={"action": "approve"}), config
    )
    assert any(event[2] == REPORT_PROGRESS for event in resume_events)

    refusal_events = await collect(
        compiled,
        build_initial_orchestrator_state("write me a report"),
        _config("report-writers-2"),
    )
    assert any(
        event[2] == {"type": "notice", "text": NO_MATERIAL_NOTICE}
        for event in refusal_events
    )


@pytest.mark.anyio
async def test_report_branch_resumes_and_streams_from_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    compiled = _compiled()
    config = _config("report-resume-stream-1")
    await _seed_researched_turn(compiled, monkeypatch, config)
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First", "Second"])
    await compiled.ainvoke(
        build_initial_orchestrator_state("write me a report"), config=config
    )
    _stub_report_client(monkeypatch, "The report text.")

    events = [
        event
        async for event in compiled.astream(
            Command(resume={"action": "approve"}),
            config=config,
            stream_mode="messages",
            subgraphs=True,
        )
    ]
    write_events = [
        event for event in events if event[1][1].get("langgraph_node") == "write"
    ]

    assert write_events
    assert "".join(event[1][0].text() for event in write_events) == "The report text."


@pytest.mark.anyio
async def test_report_branch_does_not_rerun_outline_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    compiled = _compiled()
    config = _config("report-resume-outline-1")
    await _seed_researched_turn(compiled, monkeypatch, config)
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First", "Second"])
    await compiled.ainvoke(
        build_initial_orchestrator_state("write me a report"), config=config
    )
    _stub_report_client(monkeypatch, "The report.")

    await compiled.ainvoke(Command(resume={"action": "approve"}), config=config)
    state = compiled.get_state(config=config)

    assert state.next == ()
    assert state.values["messages"][-1].text() == "The report."
    assert len(outline_calls) == 1


@pytest.mark.anyio
async def test_query_on_a_paused_thread_supersedes_the_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    compiled = _compiled()
    config = _config("report-supersede-1")
    await _seed_researched_turn(compiled, monkeypatch, config)
    _route(monkeypatch, "report")
    _stub_outline_model(monkeypatch, outline_calls, ["First"])
    await compiled.ainvoke(
        build_initial_orchestrator_state("write me a report"), config=config
    )
    paused = compiled.get_state(config=config)
    assert paused.next == ("reporter",)

    _route(monkeypatch, "other")

    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield "assistant reply"

    monkeypatch.setattr(chat_module, "astream_messages", stream)
    await compiled.ainvoke(
        build_initial_orchestrator_state("hello again"), config=config
    )
    state = compiled.get_state(config=config)

    assert state.next == ()
    assert state.values["messages"][-1].content == "assistant reply"
