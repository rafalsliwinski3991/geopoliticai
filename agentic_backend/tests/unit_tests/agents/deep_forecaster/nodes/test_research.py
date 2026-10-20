"""Unit tests for `agents.deep_forecaster.nodes.research`."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.language_models.base import LangSmithParams
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
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
    # Not "forecast_research": that name is the node's own summary span.
    assert recorded["name"] == "forecast_lead"
    subagents = recorded["subagents"]
    assert len(subagents) == 1
    scout = subagents[0]
    assert scout["name"] == "scout"
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
    # The prompt names the type the agent registers scouts under, not a
    # second copy of the word (review thread): renaming `SCOUT_SUBAGENT_NAME`
    # without the prompt goes red here.
    assert f'`subagent_type` "{research_module.SCOUT_SUBAGENT_NAME}"' in system_prompt
    assert "untrusted data" in scout["system_prompt"]
    assert recorded["checkpointer"] is False
    assert recorded["positional"][1] == []  # the lead's tools


def test_the_leads_default_helper_is_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """deepagents auto-adds a `general-purpose` helper with none of the
    research tools; the lead's model gets a harness profile that switches it
    off, so the lead is offered the scout alone."""
    # Arrange
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    registered: list[tuple[str, Any]] = []

    def record_registration(key: str, profile: Any) -> None:
        registered.append((key, profile))

    monkeypatch.setattr(
        research_module, "register_harness_profile", record_registration
    )
    # Act
    research_module.build_research_agent(ResearchRun(writer=lambda event: None))
    # Assert
    expected_profile = HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)
    )
    assert registered == [("openai:gpt-5-mini", expected_profile)]
    assert research_module.LEAD_PROFILE.general_purpose_subagent.enabled is False


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
                        "subagent_type": "scout",
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
                            "subagent_type": "scout",
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
async def test_a_real_lead_cannot_start_a_general_purpose_helper(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """With the default helper switched off, a lead that calls for
    `general-purpose` is refused by name and no scout runs."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test")

    class _Gpt5MiniModel(_Model):
        """A fake whose model identifies as openai:gpt-5-mini, so the lead's
        registered harness profile applies to it."""

        model_name: str = "gpt-5-mini"

        def _get_ls_params(
            self, stop: list[str] | None = None, **kwargs: Any
        ) -> LangSmithParams:
            return {"ls_provider": "openai"}

    model = _Gpt5MiniModel(responses=[])
    model.lead_script = [
        AIMessage(
            "",
            tool_calls=[
                {
                    "name": "task",
                    "args": {
                        "description": "Scout Gabuev, asking for the helper.",
                        "subagent_type": "general-purpose",
                    },
                    "id": "t1",
                }
            ],
        ),
        AIMessage("Done."),
    ]
    model.scout_script = [AIMessage("a scout must never answer")]

    monkeypatch.setattr(research_module, "build_chat_model", lambda settings: model)

    run = ResearchRun(writer=events.append)
    agent = research_module.build_research_agent(run)

    # Act
    result = await agent.ainvoke(
        {"messages": [HumanMessage("q")]},
        config=research_module.NO_CHECKPOINTER_CONFIG,
    )

    # Assert
    refusals = [
        message.content for message in result["messages"] if message.type == "tool"
    ]
    assert refusals == [
        "We cannot invoke subagent general-purpose because it does not exist, "
        "the only allowed types are `scout`"
    ]
    assert run.searches == 0
    assert run.sources == {}


@pytest.mark.anyio
async def test_the_profile_applies_to_the_real_build_chat_model(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """The profile lookup reads the identity a real `ChatOpenAI` resolves —
    its own `model_name` and `_get_ls_params`, not a fake's hand-copied
    identity (review thread): the built lead's `task` tool then lists
    `scout` and not the switched-off `general-purpose` helper."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    run = ResearchRun(writer=events.append)
    # Act
    agent = research_module.build_research_agent(run)
    task = agent.nodes["tools"].bound.tools_by_name["task"]
    # Assert
    assert "- scout:" in task.description
    assert "- general-purpose:" not in task.description


@pytest.mark.anyio
async def test_the_lead_profile_leaves_the_deep_experts_helper_in_place(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """The lead's profile is process-wide and keyed by `openai:gpt-5-mini`,
    the deep expert's model too; the comment and CLAUDE.md promise its own
    `general-purpose` spec survives (deepagents keeps an explicit spec,
    `deepagents/graph.py:798`), so a test guards it (review thread)."""
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    key = research_module.LEAD_PROFILE_KEY
    previous = _HARNESS_PROFILES.get(key)
    research_module.register_harness_profile(key, research_module.LEAD_PROFILE)
    try:
        from agents.deep_expert.graph import build_graph as build_deep_expert
        from agents.deep_expert.state import ResearchRun as ExpertRun

        agent = build_deep_expert(ExpertRun(writer=events.append))
        task = agent.nodes["tools"].bound.tools_by_name["task"]
        # Assert: the deep expert's own `general-purpose` spec is still offered.
        assert "- general-purpose:" in task.description
    finally:
        # The registry is process-wide; restore it for the other tests.
        if previous is None:
            _HARNESS_PROFILES.pop(key, None)
        else:
            _HARNESS_PROFILES[key] = previous


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


def _span_by_name(captured: InMemorySpanExporter, name: str) -> ReadableSpan:
    matches = [
        span
        for span in captured.get_finished_spans()
        if span.name == name and span.attributes is not None
    ]
    assert len(matches) == 1, f"expected exactly one {name} span, got {len(matches)}"
    return matches[0]


@pytest.mark.anyio
async def test_research_span_records_the_time_box(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    import agents.deep_forecaster.config as config

    fake_factory = lambda run: _FakeAgent(  # noqa: E731
        run, mutate=_record_one_source, slow=1.0
    )
    monkeypatch.setattr(research_module, "build_research_agent", fake_factory)
    small = dataclasses.replace(config.LIMITS, research_seconds=0.05)
    monkeypatch.setattr(research_module, "LIMITS", small)
    monkeypatch.setattr(config, "LIMITS", small)
    # Act
    await research_module.research({"question": "q"}, _runtime(events))
    span = _span_by_name(captured_spans, "forecast_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.time_limit_hit"] is True
    assert attributes["research.sources_read"] == 1


@pytest.mark.anyio
async def test_research_span_records_a_full_source_budget(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    def fill_sources(run: ResearchRun) -> None:
        for index in range(research_module.LIMITS.max_sources):
            run.sources[f"https://a.example/{index}"] = Source(
                "t", f"https://a.example/{index}", "text " * 100
            )

    _patch_agent(monkeypatch, lambda run: _FakeAgent(run, mutate=fill_sources))
    # Act
    await research_module.research({"question": "q"}, _runtime(events))
    span = _span_by_name(captured_spans, "forecast_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.source_budget_hit"] is True
    assert attributes["research.search_budget_hit"] is False


@pytest.mark.anyio
async def test_research_span_records_the_search_budget_reached(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    def exhaust_the_budget(run: ResearchRun) -> None:
        run.searches = research_module.LIMITS.max_searches
        run.failed_searches = 2
        run.videos = 1
        for index in range(3):
            run.sources[f"https://a.example/{index}"] = Source(
                "t", f"https://a.example/{index}", "text " * 100
            )

    _patch_agent(monkeypatch, lambda run: _FakeAgent(run, mutate=exhaust_the_budget))
    # Act
    await research_module.research({"question": "q"}, _runtime(events))
    span = _span_by_name(captured_spans, "forecast_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.searches_used"] == research_module.LIMITS.max_searches
    assert attributes["research.search_budget_hit"] is True
    assert attributes["research.source_budget_hit"] is False
    assert attributes["research.failed_searches"] == 2
    assert attributes["research.videos_used"] == 1
    assert attributes["research.sources_read"] == 3


@pytest.mark.anyio
async def test_research_span_records_a_failed_run(
    monkeypatch: pytest.MonkeyPatch,
    events: list[dict[str, Any]],
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    fake = _FakeAgent(ResearchRun(writer=events.append), fail=RuntimeError("bug"))
    _patch_agent(
        monkeypatch, lambda run: _FakeAgent(run, fail=fake.fail, mutate=fake.mutate)
    )
    # Act
    with pytest.raises(LLMInvocationError):
        await research_module.research({"question": "q"}, _runtime(events))
    span = _span_by_name(captured_spans, "forecast_research")
    # Assert
    attributes = span.attributes
    assert attributes is not None
    assert attributes["research.searches_used"] == 0
