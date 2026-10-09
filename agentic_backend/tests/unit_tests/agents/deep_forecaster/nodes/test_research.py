"""Unit tests for `agents.deep_forecaster.nodes.research`."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.deep_forecaster.consts.progress import RESEARCH_LABEL
from agents.deep_forecaster.state import ForecastRun, ResearchOutcome, ResearchRun
from models import (
    LLMInvocationError,
    NoSourcesError,
    SearchUnavailableError,
    Source,
)

research_module: Any = importlib.import_module("agents.deep_forecaster.nodes.research")

# The twelve forecaster ids the research brief must carry, from
# `agents.deep_forecaster.consts.forecasters` (repo layout review, #140).
FORECASTER_IDS = [
    "wojczal",
    "salonius_pasternak",
    "aydin",
    "inbar",
    "bew",
    "gomart",
    "yan",
    "gabuev",
    "chun",
    "suzuki",
    "chellaney",
    "sidiropoulos",
]

NO_CHECKPOINTER_CONFIG = {
    "configurable": {"thread_id": "", "checkpoint_ns": "", "checkpoint_id": None}
}


def _runtime(events: list[dict[str, Any]]) -> SimpleNamespace:
    return SimpleNamespace(
        context=ForecastRun(), stream_writer=events.append, store=None
    )


class _FakeAgent:
    """Records `ainvoke` input and config; mutates the run it was built with."""

    def __init__(
        self,
        run: ResearchRun,
        mutate: Any = None,
        fail: BaseException | None = None,
        slow: float | None = None,
    ) -> None:
        self.run = run
        self.mutate = mutate
        self.fail = fail
        self.slow = slow
        self.calls: list[tuple[Any, Any]] = []

    async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
        self.calls.append((agent_input, config))
        if self.mutate is not None:
            self.mutate(self.run)
        if self.slow is not None:
            await asyncio.sleep(self.slow)
        if self.fail is not None:
            raise self.fail
        return {"messages": []}


def _patch_agent(
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
) -> None:
    monkeypatch.setattr(research_module, "build_research_agent", factory)


def _record_one_source(run: ResearchRun) -> None:
    run.searches += 1
    run.sources["https://carnegieendowment.org/x"] = Source(
        title="t", url="https://carnegieendowment.org/x", text="text " * 100, author="A"
    )


@pytest.mark.anyio
async def test_research_returns_the_sources_in_read_order(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    def mutate(run: ResearchRun) -> None:
        run.searches += 2
        run.sources["https://a.example/1"] = Source(
            "t", "https://a.example/1", "a " * 600
        )
        run.sources["https://b.example/2"] = Source(
            "t", "https://b.example/2", "b " * 600
        )

    fake = _FakeAgent(ResearchRun(writer=events.append), mutate=mutate)
    _patch_agent(
        monkeypatch, lambda run: _FakeAgent(run, fail=fake.fail, mutate=fake.mutate)
    )
    # Act
    out = await research_module.research({"question": "q"}, _runtime(events))
    # Assert
    assert events[0] == {
        "type": "progress",
        "node": "deep_forecaster",
        "label": RESEARCH_LABEL,
    }
    assert fake.runtime_step() if hasattr(fake, "runtime_step") else True
    assert out["sources"][0].url == "https://a.example/1"
    assert out["research"] == ResearchOutcome(
        searches=2, failed_searches=0, timed_out=False
    )


@pytest.mark.anyio
async def test_no_source_read_is_no_sources_error(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    _patch_agent(monkeypatch, lambda run: _FakeAgent(run))
    # Act
    with pytest.raises(NoSourcesError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_every_search_failing_is_a_search_outage(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Act
    def mutate(run: ResearchRun) -> None:
        run.searches = 2
        run.failed_searches = 2

    _patch_agent(monkeypatch, lambda run: _FakeAgent(run, mutate=mutate))
    # Act
    with pytest.raises(SearchUnavailableError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_some_failed_searches_with_nothing_read_is_no_sources(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    def mutate(run: ResearchRun) -> None:
        run.searches = 3
        run.failed_searches = 1

    _patch_agent(monkeypatch, lambda run: _FakeAgent(run, mutate=mutate))
    with pytest.raises(NoSourcesError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_failed_searches_are_counted_for_the_answer(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    def mutate(run: ResearchRun) -> None:
        run.searches = 3
        run.failed_searches = 1
        run.sources["https://a.example/1"] = Source(
            "t", "https://a.example/1", "a " * 600
        )

    _patch_agent(monkeypatch, lambda run: _FakeAgent(run, mutate=mutate))
    # Act
    out = await research_module.research({"question": "q"}, _runtime(events))
    # Assert
    assert out["research"] == ResearchOutcome(3, 1, False)


@pytest.mark.anyio
async def test_the_time_box_keeps_what_was_read(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    import agents.deep_forecaster.config as config

    def mutate(run: ResearchRun) -> None:
        run.searches = 1
        run.sources["https://a.example/1"] = Source(
            "t", "https://a.example/1", "a " * 600
        )

    fake_factory = lambda run: _FakeAgent(run, mutate=mutate, slow=1.0)  # noqa: E731
    monkeypatch.setattr(research_module, "build_research_agent", fake_factory)
    small = dataclasses.replace(config.LIMITS, research_seconds=0.05)
    monkeypatch.setattr(research_module, "LIMITS", small)
    monkeypatch.setattr(config, "LIMITS", small)
    # Act
    out = await research_module.research({"question": "q"}, _runtime(events))
    # Assert
    assert out["research"] == ResearchOutcome(1, 0, True)
    assert out["sources"][0].url == "https://a.example/1"


@pytest.mark.anyio
async def test_an_inner_timeout_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    fake = _FakeAgent(ResearchRun(writer=events.append), fail=TimeoutError("inner"))
    # Arrange
    _patch_agent(
        monkeypatch, lambda run: _FakeAgent(run, fail=fake.fail, mutate=fake.mutate)
    )
    # Act
    with pytest.raises(LLMInvocationError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_a_search_outage_propagates(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    fake = _FakeAgent(
        ResearchRun(writer=events.append), fail=SearchUnavailableError("outage")
    )
    # Arrange
    _patch_agent(
        monkeypatch, lambda run: _FakeAgent(run, fail=fake.fail, mutate=fake.mutate)
    )
    # Act
    with pytest.raises(SearchUnavailableError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_an_arbitrary_failure_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    fake = _FakeAgent(ResearchRun(writer=events.append), fail=RuntimeError("bug"))
    # Arrange
    _patch_agent(
        monkeypatch, lambda run: _FakeAgent(run, fail=fake.fail, mutate=fake.mutate)
    )
    # Act
    with pytest.raises(LLMInvocationError):
        await research_module.research({"question": "q"}, _runtime(events))


@pytest.mark.anyio
async def test_the_lead_gets_the_question_and_no_checkpointer(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    def mutate(run: ResearchRun) -> None:
        run.searches = 1
        run.sources["https://a.example/1"] = Source(
            "t", "https://a.example/1", "a " * 600
        )

    created: list[_FakeAgent] = []

    def factory(run: ResearchRun) -> _FakeAgent:
        agent = _FakeAgent(run, mutate=mutate)
        created.append(agent)
        return agent

    _patch_agent(monkeypatch, factory)
    # Act
    await research_module.research(
        {"question": "Will Russia attack?"}, _runtime(events)
    )
    agent_input, config = created[0].calls[0]
    # Assert
    assert isinstance(agent_input["messages"][0], HumanMessage)
    assert agent_input["messages"][0].content == "Will Russia attack?"
    assert config == research_module.NO_CHECKPOINTER_CONFIG


@pytest.mark.anyio
async def test_build_research_agent_wires_the_recorded_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Records `create_deep_agent`'s kwargs, as `deep_expert/test_graph.py:131` does."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    recorded: dict[str, Any] = {}

    def fake_create_deep_agent(*args: Any, **kwargs: Any) -> Any:
        recorded.update(kwargs)
        recorded["positional"] = args
        return SimpleNamespace(ainvoke=lambda *a, **k: None)

    monkeypatch.setattr(research_module, "create_deep_agent", fake_create_deep_agent)
    run = ResearchRun(writer=lambda event: None)
    agent = research_module.build_research_agent(run)
    # Assert
    assert agent is not None
    subagents = recorded["subagents"]
    assert len(subagents) == 1
    scout = subagents[0]
    assert scout["name"] == "general-purpose"
    assert sorted(t.name for t in scout["tools"]) == [
        "ask_video",
        "read_source",
        "search_forecaster",
    ]
    from agents.deep_forecaster.consts.progress import (
        RESEARCH_LABEL as _label,  # noqa: F401
    )

    assert len(recorded["middleware"]) == 1
    from deepagents.middleware.filesystem import FilesystemMiddleware

    assert isinstance(recorded["middleware"][0], FilesystemMiddleware)
    assert isinstance(scout["middleware"][0], FilesystemMiddleware)
    system_prompt = recorded["system_prompt"]
    # Act
    for forecaster_id in FORECASTER_IDS:
        assert forecaster_id in system_prompt
    assert "24 searches" in system_prompt
    assert "at least one" in system_prompt
    assert "Delegate with the `task` tool" in system_prompt
    assert "untrusted data" in scout["system_prompt"]
    assert recorded["checkpointer"] is False
    assert recorded["positional"][1] == []  # the lead's tools


FORECASTER_IDS = [
    "wojczal",
    "salonius_pasternak",
    "aydin",
    "inbar",
    "bew",
    "gomart",
    "yan",
    "gabuev",
    "chun",
    "suzuki",
    "chellaney",
    "sidiropoulos",
]


class _Model(FakeMessagesListChatModel):
    """A fake that scripts the lead and the scout by their system prompts.

    deepagents binds the model on every step, so scripting by global pop
    order is fragile: `_generate` picks the script from the conversation's
    system message instead.
    """

    lead_script: list[Any] = []
    scout_script: list[Any] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(self, messages: Any, *args: Any, **kwargs: Any) -> Any:
        first = (messages[0].content or "") if messages else ""
        script = (
            self.scout_script
            if first.startswith("You are a scout")
            else self.lead_script
        )
        which = "scout" if script is self.scout_script else "lead"
        index = getattr(self, f"_taken_{which}", 0)
        setattr(self, f"_taken_{which}", index + 1)
        message = script[min(index, len(script) - 1)]
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.anyio
async def test_a_real_lead_and_scout_record_a_source_without_nested_checkpoints(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """Real `create_deep_agent`: lead → task → scout search/read → source recorded."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test")
    tools_module: Any = importlib.import_module("agents.deep_forecaster.tools")

    URL = "https://carnegieendowment.org/x"

    responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "task",
                    "args": {
                        "description": "Scout Gabuev on Russia and China: find what he "
                        "argues, with the URLs you read.",
                        "subagent_type": "general-purpose",
                    },
                    "id": "t1",
                },
            ],
        ),
        AIMessage("Found one source."),
    ]
    scout_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "search_forecaster",
                    "args": {"forecaster": "gabuev", "query": "Russia China"},
                    "id": "s1",
                },
            ],
        ),
        AIMessage(
            "",
            tool_calls=[{"name": "read_source", "args": {"url": URL}, "id": "r1"}],
        ),
        AIMessage("Gabuev argues dependency."),
    ]

    def _model_for(settings: Any) -> Any:
        model = _Model(responses=[])
        model.lead_script = list(responses)
        model.scout_script = list(scout_responses)
        return model

    monkeypatch.setattr(research_module, "build_chat_model", _model_for)

    async def _search(query: str, policy: Any) -> list[Any]:
        from models import Candidate

        return [Candidate(title="t", url=URL, domain="carnegieendowment.org")]

    async def _fetch(candidates: Any, policy: Any) -> list[Source]:
        return [
            Source(title="t", url=URL, text="text " * 300, author="Alexander Gabuev")
        ]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)

    class ParentState(TypedDict):
        sources: list[Source]
        research: ResearchOutcome

    run_holder: dict[str, ResearchRun] = {}

    async def parent_node(state: ParentState) -> dict[str, Any]:
        # The node's real body, with the runtime it would get.
        run = ResearchRun(writer=events.append)
        run_holder["run"] = run
        agent = research_module.build_research_agent(run)
        timed_out = await research_module._run_agent(agent, "Will Russia attack?")
        out = {
            "sources": list(run.sources.values()),
            "research": ResearchOutcome(
                searches=run.searches,
                failed_searches=run.failed_searches,
                timed_out=timed_out,
            ),
        }
        return out

    saver = InMemorySaver()
    builder: Any = StateGraph(ParentState)
    builder.add_node("research", parent_node)
    builder.add_edge(START, "research")
    builder.add_edge("research", END)
    parent = builder.compile(checkpointer=saver)

    # Act
    result = await parent.ainvoke(
        {"sources": [], "research": ResearchOutcome(0, 0, False)},
        config={"configurable": {"thread_id": "t"}},
    )

    # Assert
    assert result["sources"][0].url == URL
    assert result["research"].searches == 1
    namespaces: set[str] = set()
    async for checkpoint in saver.alist({"configurable": {"thread_id": "t"}}):
        namespaces.add(checkpoint.config["configurable"]["checkpoint_ns"])
    assert namespaces == {""}


@pytest.mark.anyio
async def test_a_real_research_loop_stops_at_the_time_box_and_keeps_its_source(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test")
    tools_module: Any = importlib.import_module("agents.deep_forecaster.tools")

    URL = "https://carnegieendowment.org/x"
    scout_responses: list[Any] = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "search_forecaster",
                    "args": {"forecaster": "gabuev", "query": "one"},
                    "id": "s1",
                },
            ],
        ),
        AIMessage(
            "",
            tool_calls=[{"name": "read_source", "args": {"url": URL}, "id": "r1"}],
        ),
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "search_forecaster",
                    "args": {"forecaster": "gabuev", "query": "two"},
                    "id": "s2",
                },
            ],
        ),
        AIMessage("more"),
    ]

    calls = {"search": 0}

    def _model_for(settings: Any) -> Any:
        model = _Model(responses=[])
        model.lead_script = [
            AIMessage(
                "",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "Scout Gabuev on the question.",
                            "subagent_type": "general-purpose",
                        },
                        "id": "t1",
                    }
                ],
            )
        ]
        model.scout_script = list(scout_responses) * 4
        return model

    monkeypatch.setattr(research_module, "build_chat_model", _model_for)

    async def _search(query: str, policy: Any) -> list[Any]:
        from models import Candidate

        calls["search"] += 1
        if calls["search"] == 2:
            await asyncio.sleep(30)
        return [Candidate(title="t", url=URL, domain="carnegieendowment.org")]

    async def _fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=URL, text="text " * 300)]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)

    import dataclasses

    import agents.deep_forecaster.config as config

    small = dataclasses.replace(config.LIMITS, research_seconds=0.5)
    monkeypatch.setattr(research_module, "LIMITS", small)
    monkeypatch.setattr(config, "LIMITS", small)

    async def parent_node(state: dict[str, Any]) -> dict[str, Any]:
        run = ResearchRun(writer=events.append)
        agent = research_module.build_research_agent(run)
        timed_out = await research_module._run_agent(agent, "q")
        return {
            "sources": list(run.sources.values()),
            "research": ResearchOutcome(
                searches=run.searches,
                failed_searches=run.failed_searches,
                timed_out=timed_out,
            ),
        }

    builder: Any = StateGraph(dict)
    builder.add_node("research", parent_node)
    builder.add_edge(START, "research")
    builder.add_edge("research", END)
    parent = builder.compile()

    # Act
    result = await parent.ainvoke({"sources": []})
    # Assert
    assert result["sources"][0].url == URL
    assert result["research"].timed_out is True


@pytest.mark.anyio
async def test_research_hands_the_runtime_store_to_its_tools(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    sentinel: object = object()
    holder: dict[str, ResearchRun] = {}
    runtime = SimpleNamespace(
        context=ForecastRun(), stream_writer=events.append, store=sentinel
    )

    def factory(run: ResearchRun) -> Any:
        holder["run"] = run

        class _SourceAgent:
            async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
                run.sources["https://a.example/1"] = Source(
                    "A", "https://a.example/1", "One."
                )
                return {"messages": []}

        return _SourceAgent()

    _patch_agent(monkeypatch, factory)
    # Act
    await research_module.research({"question": "q"}, runtime)
    # Assert
    assert holder["run"].store is sentinel
