"""Unit tests for `agents.deep_expert.graph`."""

from __future__ import annotations

import importlib
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.deep_expert.state import ResearchRun

graph_module: Any = importlib.import_module("agents.deep_expert.graph")

DEEP_ANSWER = "A" * 10_000


def _rubric_messages() -> list[Any]:
    ai_with_tools = AIMessage(
        "",
        tool_calls=[
            {"name": "search_sources", "args": {"query": "q"}, "id": "t1"},
        ],
    )
    return [
        HumanMessage("q"),
        ai_with_tools,
        ToolMessage("x" * 20_000, tool_call_id="t1"),
        HumanMessage("revise", additional_kwargs={"lc_source": "rubric_grader"}),
        AIMessage(DEEP_ANSWER),
    ]


def test_grader_view_hands_over_the_question_and_the_whole_draft() -> None:
    # Act
    view = graph_module.grader_view(_rubric_messages())

    # Assert
    assert isinstance(view[0], HumanMessage)
    assert view[0].content == "q"
    assert all(isinstance(m, AIMessage) for m in view[1:])
    assert len(view) == 4


def test_each_part_fits_the_cut_and_joins_back() -> None:
    # Act
    view = graph_module.grader_view(_rubric_messages())

    # Assert
    for index, message in enumerate(view[1:], start=1):
        assert len(message.text) <= 4_000
        assert message.text.startswith(f"(final answer, part {index} of 3)\n")
    joined = "".join(
        message.text.removeprefix(f"(final answer, part {index} of 3)\n")
        for index, message in enumerate(view[1:], start=1)
    )
    assert joined == DEEP_ANSWER


@pytest.mark.parametrize(
    ("length", "parts"),
    [(0, 1), (3_900, 1), (3_901, 2), (7_800, 2)],
    ids=["empty_fallback", "exact_single", "one_over", "exact_double"],
)
def test_grader_view_parts_round_trip_exactly(length: int, parts: int) -> None:
    """The fallback, exact multiples, and one-over splits all round-trip.

    Length 0 pins the `or [""]` fallback (one empty part, no IndexError);
    3_900 and 7_800 pin the exact-multiple boundaries of GRADER_PART_CHARS;
    3_901 pins the one-over split.
    """
    # Arrange
    draft = "A" * length
    messages: list[Any] = [HumanMessage("q"), AIMessage(draft)]

    # Act
    view = graph_module.grader_view(messages)

    # Assert
    assert len(view) == parts + 1
    joined = "".join(
        message.text.removeprefix(f"(final answer, part {index} of {parts})\n")
        for index, message in enumerate(view[1:], start=1)
    )
    assert joined == draft


def test_no_tool_message_survives() -> None:
    # Act + Assert
    assert not any(
        isinstance(m, ToolMessage) for m in graph_module.grader_view(_rubric_messages())
    )


def test_a_view_without_a_question_is_returned_unchanged() -> None:
    # Arrange
    messages: list[Any] = [AIMessage("a")]

    # Act + Assert
    assert graph_module.grader_view(messages) is messages


@pytest.mark.anyio
async def test_build_graph_compiles_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    run = SimpleNamespace(record_evaluation=lambda e: None)

    # Act
    graph = graph_module.build_graph(run)

    # Assert
    nodes = set(graph.get_graph().nodes)
    assert {"model", "tools"} <= nodes


@pytest.mark.anyio
async def test_importing_the_package_without_a_key_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Act + Assert
    importlib.reload(graph_module)


@pytest.mark.anyio
async def test_build_graph_wires_the_recorded_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    recorded_deep: dict[str, Any] = {}
    recorded_rubric: dict[str, Any] = {}

    real_create = graph_module.create_deep_agent
    real_rubric = graph_module.RubricMiddleware

    def recording_create(*args: Any, **kwargs: Any) -> Any:
        recording_kwargs = dict(zip(list(signature(real_create).parameters), args))
        recording_kwargs.update(kwargs)
        recorded_deep.update(recording_kwargs)
        return real_create(*args, **kwargs)

    def recording_rubric(*args: Any, **kwargs: Any) -> Any:
        recorded_rubric.update(kwargs)
        return real_rubric(*args, **kwargs)

    monkeypatch.setattr(graph_module, "create_deep_agent", recording_create)
    monkeypatch.setattr(graph_module, "RubricMiddleware", recording_rubric)
    run = SimpleNamespace(record_evaluation=lambda e: None)

    # Act
    graph_module.build_graph(run)

    # Assert
    tool_names = [tool.name for tool in recorded_deep["tools"]]
    assert sorted(tool_names) == ["read_source", "search_sources"]
    # The subagent shares this turn's tool objects, so both agents spend from
    # the same budget (`ResearchRun`).
    assert recorded_deep["subagents"][0]["tools"] is recorded_deep["tools"]
    assert recorded_deep["subagents"][0]["model"] is recorded_deep["model"]
    assert "at most 5 searches" in recorded_deep["system_prompt"]
    subagent = recorded_deep["subagents"][0]
    assert subagent["name"] == "general-purpose"
    assert "untrusted data" in subagent["system_prompt"]
    middleware = recorded_deep["middleware"]
    types = [type(m).__name__ for m in middleware]
    assert types.count("TodoListMiddleware") == 1
    assert types.count("RubricMiddleware") == 1
    assert recorded_deep["checkpointer"] is False
    assert recorded_rubric["max_iterations"] == 3
    assert recorded_rubric["on_evaluation"] == run.record_evaluation
    assert recorded_rubric["prepare_messages_for_grader"] is graph_module.grader_view


@pytest.mark.anyio
async def test_the_whole_loop_propagates_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ToolNode re-raises app exceptions through the real create_deep_agent."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import StreamWriter
    from typing_extensions import TypedDict

    from models import SearchUnavailableError

    tools_module: Any = importlib.import_module("agents.deep_expert.tools")
    research_module: Any = importlib.import_module("agents.deep_expert.research")

    class ParentState(TypedDict):
        marker: str

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        await research_module.research("q", writer)
        return {"marker": "unreached"}

    async def _boom(query: Any, policy: Any) -> list[Any]:
        raise SearchUnavailableError("brave down")

    monkeypatch.setattr(tools_module, "search_allowlisted", _boom)

    class _Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    search_call = AIMessage(
        "",
        tool_calls=[
            {"name": "search_sources", "args": {"query": "q"}, "id": "t1"},
        ],
    )
    model = _Model(responses=[search_call, AIMessage("done")])
    monkeypatch.setattr(graph_module, "build_chat_model", lambda settings: model)

    builder: "StateGraph[ParentState]" = StateGraph(ParentState)
    builder.add_node("deep", parent_node)
    builder.add_edge(START, "deep")
    builder.add_edge("deep", END)
    parent: Any = builder.compile(checkpointer=InMemorySaver())

    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await parent.ainvoke(
            {"marker": ""}, config={"configurable": {"thread_id": "t"}}
        )


@pytest.mark.anyio
async def test_happy_path_and_no_nested_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real loop inside a checkpointed parent: answer returned, grader uncached."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import StreamWriter
    from typing_extensions import TypedDict

    from agents.deep_expert.config import AGENT_LLM_SETTINGS
    from models import Candidate, Source

    tools_module: Any = importlib.import_module("agents.deep_expert.tools")
    research_module: Any = importlib.import_module("agents.deep_expert.research")

    URL = "https://reuters.com/x"

    class _Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    agent_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {"name": "search_sources", "args": {"query": "q"}, "id": "s1"},
            ],
        ),
        AIMessage(
            "",
            tool_calls=[{"name": "read_source", "args": {"url": URL}, "id": "r1"}],
        ),
        AIMessage(f"Answer [a]({URL})."),
    ]
    grader_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "GraderResponse",
                    "args": {
                        "result": "satisfied",
                        "explanation": "ok",
                        "criteria": [{"name": "c", "passed": True}],
                    },
                    "id": "g1",
                }
            ],
        )
    ]

    async def _search(query: Any, policy: Any) -> list[Candidate]:
        return [Candidate(title="t", url=URL, domain="reuters.com")]

    async def _fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=URL, text="text")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)

    def _model_for(settings: Any) -> Any:
        if settings is AGENT_LLM_SETTINGS:
            return _Model(responses=agent_responses)
        return _Model(responses=grader_responses)

    monkeypatch.setattr(graph_module, "build_chat_model", _model_for)

    class ParentState(TypedDict):
        marker: str

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        deep_answer = await research_module.research("q", writer)
        return {"marker": deep_answer}

    saver = InMemorySaver()
    builder: "StateGraph[ParentState]" = StateGraph(ParentState)
    builder.add_node("deep", parent_node)
    builder.add_edge(START, "deep")
    builder.add_edge("deep", END)
    parent: Any = builder.compile(checkpointer=saver)

    # Act
    result = await parent.ainvoke(
        {"marker": ""}, config={"configurable": {"thread_id": "t"}}
    )

    # Assert: the answer came back whole.
    assert result["marker"] == f"Answer [a]({URL})."
    # And the only checkpointed namespace is the parent's: no nested
    # `deep_expert:` namespace for the agent, subagent, or grader runs.
    namespaces: set[str] = set()
    async for checkpoint in saver.alist({"configurable": {"thread_id": "t"}}):
        namespaces.add(checkpoint.config["configurable"]["checkpoint_ns"])
    assert namespaces == {""}


def _revised_loop_modules() -> tuple[Any, Any]:
    """Return `(tools_module, research_module)`, imported the way the loop tests need."""
    tools_module: Any = importlib.import_module("agents.deep_expert.tools")
    research_module: Any = importlib.import_module("agents.deep_expert.research")
    return tools_module, research_module


@pytest.mark.anyio
async def test_rubric_loop_drives_revision_and_max_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real RubricMiddleware: needs_revision twice, then satisfied.

    `SHIPPABLE_VERDICTS` relies on the `needs_revision` -> revision -> loop
    behavior, and this drives it through real middleware instead of a spy.
    """
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import StreamWriter
    from typing_extensions import TypedDict

    from agents.deep_expert.config import AGENT_LLM_SETTINGS
    from models import Candidate, Source

    tools_module, research_module = _revised_loop_modules()

    URL = "https://reuters.com/x"

    class _Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    agent_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {"name": "search_sources", "args": {"query": "q"}, "id": "s1"},
            ],
        ),
        AIMessage(
            "",
            tool_calls=[{"name": "read_source", "args": {"url": URL}, "id": "r1"}],
        ),
        AIMessage("Draft one."),
        AIMessage("Draft two."),
        AIMessage(f"Final [a]({URL})."),
    ]

    def grader_response(result: str, iteration: int) -> AIMessage:
        # A failing verdict needs a `gap` on every failing criterion
        # (deepagents 0.7.19 `CriterionFail`), or the structured output
        # refuses to parse and the grader retries.
        criteria = (
            [{"name": "c", "passed": False, "gap": "thin"}]
            if result == "needs_revision"
            else [{"name": "c", "passed": True}]
        )
        return AIMessage(
            "",
            tool_calls=[
                {
                    "name": "GraderResponse",
                    "args": {
                        "result": result,
                        "explanation": "ok",
                        "criteria": criteria,
                    },
                    "id": f"g{iteration}",
                }
            ],
        )

    grader_responses = [
        grader_response("needs_revision", 1),
        grader_response("needs_revision", 2),
        grader_response("satisfied", 3),
    ]

    async def _search(query: Any, policy: Any) -> list[Candidate]:
        return [Candidate(title="t", url=URL, domain="reuters.com")]

    async def _fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=URL, text="text")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)

    def _model_for(settings: Any) -> Any:
        if settings is AGENT_LLM_SETTINGS:
            return _Model(responses=agent_responses)
        return _Model(responses=grader_responses)

    monkeypatch.setattr(graph_module, "build_chat_model", _model_for)

    class ParentState(TypedDict):
        marker: str

    events: list[dict[str, Any]] = []

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        deep_answer = await research_module.research("q", writer)
        return {"marker": deep_answer}

    captured: dict[str, Any] = {}

    def capturing_build_graph(inner_run: Any) -> Any:
        captured["run"] = inner_run
        return graph_module.build_graph(inner_run)

    monkeypatch.setattr(research_module, "build_graph", capturing_build_graph)

    builder: "StateGraph[ParentState]" = StateGraph(ParentState)
    builder.add_node("deep", parent_node)
    builder.add_edge(START, "deep")
    builder.add_edge("deep", END)
    parent: Any = builder.compile(checkpointer=InMemorySaver())

    # Act: `stream_mode="custom"` is what turns the node's `writer` into a
    # recorder; plain `ainvoke` gives it a no-op writer.
    answer: Any = None
    async for mode, chunk in parent.astream(
        {"marker": ""},
        config={"configurable": {"thread_id": "t"}},
        stream_mode=["values", "custom"],
    ):
        if mode == "custom":
            events.append(chunk)
        else:
            answer = chunk

    # Assert: the third draft ships, the verdict sequence is real, and each
    # `needs_revision` emitted its revision frame.
    assert answer["marker"] == f"Final [a]({URL})."
    inner_run: ResearchRun = captured["run"]
    assert inner_run.verdicts == ["needs_revision", "needs_revision", "satisfied"]
    labels = [event["label"] for event in events if event.get("type") == "progress"]
    assert labels.count("Revising the analysis (1 of 2)...") == 1
    assert labels.count("Revising the analysis (2 of 2)...") == 1


@pytest.mark.anyio
async def test_rubric_loop_at_max_iterations_ships_the_last_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three needs_revision verdicts end `max_iterations_reached`, which ships.

    `SHIPPABLE_VERDICTS` includes `max_iterations_reached` (brainstorm Q7A);
    the last draft goes out instead of a hard failure.
    """
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import StreamWriter
    from typing_extensions import TypedDict

    from agents.deep_expert.config import AGENT_LLM_SETTINGS
    from models import Candidate, Source

    tools_module, research_module = _revised_loop_modules()

    URL = "https://reuters.com/x"

    class _Model(FakeMessagesListChatModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    agent_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {"name": "search_sources", "args": {"query": "q"}, "id": "s1"},
            ],
        ),
        AIMessage(
            "",
            tool_calls=[{"name": "read_source", "args": {"url": URL}, "id": "r1"}],
        ),
        AIMessage("Draft one."),
        AIMessage("Draft two."),
        AIMessage(f"Draft three [a]({URL})."),
    ]

    def grader_round() -> AIMessage:
        return AIMessage(
            "",
            tool_calls=[
                {
                    "name": "GraderResponse",
                    "args": {
                        "result": "needs_revision",
                        "explanation": "not good",
                        "criteria": [{"name": "c", "passed": False, "gap": "thin"}],
                    },
                    "id": "g1",
                }
            ],
        )

    grader_responses = [grader_round(), grader_round(), grader_round()]

    async def _search(query: Any, policy: Any) -> list[Candidate]:
        return [Candidate(title="t", url=URL, domain="reuters.com")]

    async def _fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=URL, text="text")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)

    def _model_for(settings: Any) -> Any:
        if settings is AGENT_LLM_SETTINGS:
            return _Model(responses=agent_responses)
        return _Model(responses=list(grader_responses))

    monkeypatch.setattr(graph_module, "build_chat_model", _model_for)

    class ParentState(TypedDict):
        marker: str

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        deep_answer = await research_module.research("q", writer)
        return {"marker": deep_answer}

    captured: dict[str, Any] = {}

    def capturing_build_graph(inner_run: Any) -> Any:
        captured["run"] = inner_run
        return graph_module.build_graph(inner_run)

    monkeypatch.setattr(research_module, "build_graph", capturing_build_graph)

    builder: "StateGraph[ParentState]" = StateGraph(ParentState)
    builder.add_node("deep", parent_node)
    builder.add_edge(START, "deep")
    builder.add_edge("deep", END)
    parent: Any = builder.compile(checkpointer=InMemorySaver())

    # Act
    answer2: Any = None
    async for mode, chunk in parent.astream(
        {"marker": ""},
        config={"configurable": {"thread_id": "t"}},
        stream_mode=["values", "custom"],
    ):
        if mode == "values":
            answer2 = chunk

    # Assert
    assert answer2["marker"] == f"Draft three [a]({URL})."
    inner_run: ResearchRun = captured["run"]
    assert inner_run.verdicts == [
        "needs_revision",
        "needs_revision",
        "max_iterations_reached",
    ]
