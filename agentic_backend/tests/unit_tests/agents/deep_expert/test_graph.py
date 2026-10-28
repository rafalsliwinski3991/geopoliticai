"""Unit tests for `agents.deep_expert.graph`."""

from __future__ import annotations

import asyncio
import importlib
from inspect import signature
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.constants import CONFIG_KEY_CHECKPOINTER
from langgraph.errors import NodeTimeoutError
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agents.deep_expert.config import ResearchLimits
from agents.deep_expert.prompts import DEEP_ANSWER_RUBRIC
from agents.deep_expert.state import ResearchRun
from models import Source
from shared.errors import (
    LLMInvocationError,
    NoSourcesError,
    ResearchLimitError,
    SearchUnavailableError,
)
from shared.frames import ProgressFrame

graph_module: Any = importlib.import_module("agents.deep_expert.graph")

DEEP_ANSWER = "A" * 10_000
# The wall-cap test: a model call hangs far past a short cap, and the run must
# end well before the hang would have.
WALL_SECONDS = 0.2
HANG_SECONDS = 5.0
ENDED_WITHIN_SECONDS = 2.0


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

    from shared.errors import SearchUnavailableError

    tools_module: Any = importlib.import_module("agents.deep_expert.tools")
    research_module: Any = importlib.import_module("agents.deep_expert.graph")

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
    research_module: Any = importlib.import_module("agents.deep_expert.graph")

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
    research_module: Any = importlib.import_module("agents.deep_expert.graph")
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

    grader_responses: list[Any] = [
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

    events: list[object] = []

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        deep_answer = await research_module.research("q", writer)
        return {"marker": deep_answer}

    captured: dict[str, Any] = {}
    real_build_graph = graph_module.build_graph

    def capturing_build_graph(inner_run: Any) -> Any:
        captured["run"] = inner_run
        return real_build_graph(inner_run)

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
    labels = [event.label for event in events if isinstance(event, ProgressFrame)]
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
    real_build_graph = graph_module.build_graph

    def capturing_build_graph(inner_run: Any) -> Any:
        captured["run"] = inner_run
        return real_build_graph(inner_run)

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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "responses_before_hang",
    [
        [],
        [
            AIMessage(
                "",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "dig",
                            "subagent_type": graph_module.GENERAL_PURPOSE_SUBAGENT_NAME,
                        },
                        "id": "k1",
                    }
                ],
            )
        ],
    ],
    ids=["the agent's own call", "a subagent's call"],
)
async def test_the_wall_cap_ends_a_run_whose_model_call_hangs(
    monkeypatch: pytest.MonkeyPatch, responses_before_hang: list[Any]
) -> None:
    """A hung model call must not hold the turn past `LIMITS.wall_seconds`.

    The forecaster's smoke gate F3 saw a hung deepagents run outlive an
    in-frame `asyncio.timeout`; the deep expert caps its run with
    `capped_run.run_under_time_limits`, so this runs the real agent (and its
    `task` subagent) inside a checkpointed parent, as the orchestrator does, and
    hangs one model call.
    """
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import StreamWriter
    from typing_extensions import TypedDict

    from agents.deep_expert.config import ResearchLimits
    from shared.errors import ResearchLimitError

    research_module: Any = importlib.import_module("agents.deep_expert.graph")

    class _HangingModel(FakeMessagesListChatModel):
        """Plays `responses` in order, hangs on the next call, then refuses more.

        The refusal keeps a regressed cap from looping through the rubric
        grader: the test then fails in about `HANG_SECONDS` instead of hanging.
        """

        calls: int = 0

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

        async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
            self.calls += 1
            if self.calls <= len(self.responses):
                message = self.responses[self.calls - 1]
                return ChatResult(generations=[ChatGeneration(message=message)])
            if self.calls == len(self.responses) + 1:
                await asyncio.sleep(HANG_SECONDS)
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage("late"))]
                )
            raise AssertionError("the scripted model has no call left")

    model = _HangingModel(responses=responses_before_hang)
    monkeypatch.setattr(graph_module, "build_chat_model", lambda settings: model)
    monkeypatch.setattr(
        research_module, "LIMITS", ResearchLimits(wall_seconds=WALL_SECONDS)
    )

    class ParentState(TypedDict):
        marker: str

    async def parent_node(state: ParentState, writer: StreamWriter) -> dict[str, Any]:
        await research_module.research("q", writer)
        return {"marker": "unreached"}

    builder: "StateGraph[ParentState]" = StateGraph(ParentState)
    builder.add_node("deep", parent_node)
    builder.add_edge(START, "deep")
    builder.add_edge("deep", END)
    parent: Any = builder.compile(checkpointer=InMemorySaver())
    loop = asyncio.get_running_loop()
    started = loop.time()

    # Act
    with pytest.raises(ResearchLimitError) as caught:
        await parent.ainvoke(
            {"marker": ""}, config={"configurable": {"thread_id": "t"}}
        )

    # Assert
    assert loop.time() - started < ENDED_WITHIN_SECONDS
    assert model.calls == len(responses_before_hang) + 1
    assert "second limit" in str(caught.value)


CITED_DEEP_ANSWER = "Deep answer [a](https://reuters.com/x)."


def cited_run() -> Any:
    def _mutate(run: ResearchRun) -> None:
        run.verdicts.append("satisfied")
        run.sources["https://reuters.com/x"] = Source(
            title="t", url="https://reuters.com/x", text="text"
        )

    return _mutate


def verdict_run(verdict: str) -> Any:
    def _mutate(run: ResearchRun) -> None:
        run.verdicts.append(verdict)
        run.sources["https://reuters.com/x"] = Source(
            title="t", url="https://reuters.com/x", text="text"
        )

    return _mutate


def sources_only() -> Any:
    def _mutate(run: ResearchRun) -> None:
        run.sources["https://reuters.com/x"] = Source(
            title="t", url="https://reuters.com/x", text="text"
        )

    return _mutate


class _GraphSpy:
    """The fake agent: records invocations, mutates the run, returns messages."""

    def __init__(
        self,
        messages: list[Any],
        mutator: Any = None,
    ) -> None:
        self._messages = messages
        self._run: ResearchRun | None = None
        self._mutate = mutator
        self.invocations: list[tuple[dict[str, Any], Any]] = []
        self.fail_with: Any = None
        self.sleep_for: float = 0.0

    def bind_run(self, run: ResearchRun) -> "_GraphSpy":
        self._run = run
        return self

    async def ainvoke(
        self, state: dict[str, Any], config: Any = None
    ) -> dict[str, Any]:
        self.invocations.append((state, config))
        if self.fail_with is not None:
            raise self.fail_with
        if self.sleep_for:
            await asyncio.sleep(self.sleep_for)
        if self._mutate is not None and self._run is not None:
            self._mutate(self._run)
        return {"messages": self._messages}


@pytest.mark.anyio
async def test_a_satisfied_cited_answer_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events: list[object] = []
    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], cited_run())

    def _build_graph(run: ResearchRun) -> Any:
        spy.bind_run(run)
        return spy

    monkeypatch.setattr(graph_module, "build_graph", _build_graph)

    # Act
    deep_answer = await graph_module.research("q", events.append)

    # Assert
    assert deep_answer == CITED_DEEP_ANSWER
    assert events[0] == graph_module.PLANNING_PROGRESS


@pytest.mark.anyio
async def test_max_iterations_reached_ships_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy(
        [AIMessage(CITED_DEEP_ANSWER)], verdict_run("max_iterations_reached")
    )
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    deep_answer = await graph_module.research("q", lambda e: None)

    # Assert
    assert deep_answer == CITED_DEEP_ANSWER


@pytest.mark.anyio
@pytest.mark.parametrize("verdict", ["grader_error", "failed"])
async def test_a_failed_grader_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch, verdict: str
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], verdict_run(verdict))
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="grader"):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_no_verdict_at_all_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], sources_only())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_no_sources_read_is_no_sources_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy(
        [AIMessage(CITED_DEEP_ANSWER)], lambda run: run.verdicts.append("satisfied")
    )
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(NoSourcesError):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_sources_read_but_none_cited_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage("An uncited answer.")], cited_run())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="cited"):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_an_empty_answer_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([], cited_run())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_the_answer_is_found_past_a_rubric_human_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    messages: list[Any] = [
        AIMessage(CITED_DEEP_ANSWER),
        HumanMessage("revise"),
    ]
    spy = _GraphSpy(messages, cited_run())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    deep_answer = await graph_module.research("q", lambda e: None)

    # Assert
    assert deep_answer == CITED_DEEP_ANSWER


@pytest.mark.anyio
async def test_a_search_outage_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = SearchUnavailableError("brave down")
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_an_arbitrary_failure_becomes_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = ValueError("boom")
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await graph_module.research("q", lambda e: None)


def _span_by_name(captured: InMemorySpanExporter, name: str) -> ReadableSpan:
    matches = [
        span
        for span in captured.get_finished_spans()
        if span.name == name and span.attributes is not None
    ]
    assert len(matches) == 1, f"expected exactly one {name} span, got {len(matches)}"
    return matches[0]


@pytest.mark.anyio
async def test_research_span_records_a_spent_budget(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    def five_searches(run: ResearchRun) -> None:
        cited_run()(run)
        run.searches = 5

    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], five_searches)
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))
    # Act
    await graph_module.research("q", lambda e: None)
    span = _span_by_name(captured_spans, "deep_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.searches_used"] == 5
    assert attributes["research.search_budget_hit"] is True
    assert attributes["research.time_limit_hit"] is False


@pytest.mark.anyio
async def test_research_span_records_the_wall_limit(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    monkeypatch.setattr(graph_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _GraphSpy([])
    spy.sleep_for = 1.0

    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))
    # Act
    with pytest.raises(ResearchLimitError, match="0.01-second"):
        await graph_module.research("q", lambda e: None)
    span = _span_by_name(captured_spans, "deep_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.time_limit_hit"] is True
    # 0 searches: the wall ended the run below the search cap, so a constant
    # `search_budget_hit` failure cannot hide behind the at-cap asserts (review
    # thread, #193).
    assert attributes["research.search_budget_hit"] is False
    assert attributes["research.searches_used"] == 0


@pytest.mark.anyio
async def test_the_wall_time_cap_is_a_research_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(graph_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _GraphSpy([])
    spy.sleep_for = 1.0
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    run = graph_module.research("q", lambda e: None)
    # Assert
    with pytest.raises(ResearchLimitError, match="0.01-second"):
        await run


@pytest.mark.anyio
async def test_a_node_timeout_inside_the_run_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A node's own timeout is a 502 for this turn, not the wall cap's 504.

    The wall cap is a `ResearchLimitError`; a node timeout is a step's failure,
    which the deep expert has always reported as `LLMInvocationError`.
    """
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = NodeTimeoutError("deep_expert", 90.5, kind="run", run_timeout=90.0)
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Deep research failed.") as raised:
        await graph_module.research("q", lambda e: None)
    assert isinstance(raised.value.__cause__, NodeTimeoutError)


@pytest.mark.anyio
async def test_a_deep_run_that_absorbs_a_cancel_still_ends_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that swallows the cap's cancel must still end at the cap (Q4).

    Smoke gate F3, run 1 (2026-10-01): an in-frame `asyncio.timeout` let a hung
    run limp on. The cap now cancels the run's own task, so a run that absorbs
    the cancel is abandoned at the cap instead of returning its late answer.
    """

    # Arrange
    class _CancelAbsorbingSpy(_GraphSpy):
        async def ainvoke(
            self, state: dict[str, Any], config: Any = None
        ) -> dict[str, Any]:
            self.invocations.append((state, config))
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.5)
            assert self._mutate is not None and self._run is not None
            self._mutate(self._run)
            return {"messages": self._messages}

    monkeypatch.setattr(graph_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _CancelAbsorbingSpy([AIMessage(CITED_DEEP_ANSWER)], cited_run())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(ResearchLimitError, match="0.01-second"):
        await graph_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_an_inner_timeout_becomes_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TimeoutError raised inside the graph (not by the wall) is a 502.

    Without this, mapping every TimeoutError to ResearchLimitError would also
    pass the suite.
    """
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = TimeoutError()
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    call = graph_module.research("q", lambda e: None)
    # Assert
    with pytest.raises(LLMInvocationError):
        await call


@pytest.mark.anyio
async def test_the_agent_receives_the_rubric_and_the_no_checkpoint_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], cited_run())
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    await graph_module.research("the question", lambda e: None)

    # Assert
    state, config = spy.invocations[0]
    assert [type(m).__name__ for m in state["messages"]] == ["HumanMessage"]
    assert state["messages"][0].content == "the question"
    assert state["rubric"] == DEEP_ANSWER_RUBRIC
    assert config == {"configurable": {CONFIG_KEY_CHECKPOINTER: None}}


@pytest.mark.anyio
async def test_the_research_span_records_the_grader_verdicts(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A Phoenix trace alone must show how the grader judged each round, not only the last one."""

    # Arrange
    def revise_then_satisfy(run: ResearchRun) -> None:
        sources_only()(run)
        run.verdicts.extend(["needs_revision", "satisfied"])

    spy = _GraphSpy([AIMessage(CITED_DEEP_ANSWER)], revise_then_satisfy)
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    await graph_module.research("q", lambda e: None)

    # Assert
    attributes = _span_by_name(captured_spans, "deep_research").attributes
    assert attributes is not None
    assert attributes["research.grader_verdicts"] == ("needs_revision", "satisfied")
    assert attributes["research.grader_rounds"] == 2


@pytest.mark.anyio
async def test_the_research_span_records_no_verdicts_when_the_grader_never_ran(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A run that ends before the grader speaks must show zero rounds, not a missing attribute."""
    # Arrange
    monkeypatch.setattr(graph_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _GraphSpy([])
    spy.sleep_for = 1.0
    monkeypatch.setattr(graph_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    with pytest.raises(ResearchLimitError):
        await graph_module.research("q", lambda e: None)

    # Assert
    attributes = _span_by_name(captured_spans, "deep_research").attributes
    assert attributes is not None
    assert attributes["research.grader_verdicts"] == ()
    assert attributes["research.grader_rounds"] == 0
