"""Unit tests for `agents.deep_forecaster.graph`."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeTimeoutError
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from agents.deep_forecaster.models import Analysis, ClaimDiscussion
from agents.deep_forecaster.state import ForecastRun, ResearchRun
from models import LLMInvocationError, NoSourcesError, ResearchLimitError, Source
from unit_tests.agents.deep_forecaster.conftest import ballot, claims

graph_module: Any = importlib.import_module("agents.deep_forecaster.graph")
research_node: Any = importlib.import_module("agents.deep_forecaster.nodes.research")
draft_claims_node: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.draft_claims"
)
write_analysis_node: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.write_analysis"
)
council_module: Any = importlib.import_module("agents.deep_forecaster.council")

STEP_NAMES = [
    "research",
    "draft_claims",
    "council_round_1",
    "council_round_2",
    "tally",
    "write_analysis",
    "verify",
]


def test_the_graph_has_exactly_the_seven_steps() -> None:
    assert [name for name, _, _ in graph_module.STEPS] == STEP_NAMES


def test_the_steps_run_in_a_fixed_chain() -> None:
    graph = graph_module.build_graph()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert edges == {
        ("__start__", "research"),
        ("research", "draft_claims"),
        ("draft_claims", "council_round_1"),
        ("council_round_1", "council_round_2"),
        ("council_round_2", "tally"),
        ("tally", "write_analysis"),
        ("write_analysis", "verify"),
        ("verify", "__end__"),
    }


def test_no_step_is_named_like_an_answer_node() -> None:
    names = {name for name, _, _ in graph_module.STEPS}
    assert names & {"answer", "chat", "write"} == set()


def test_build_graph_needs_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    graph_module.build_graph()


def test_the_single_call_steps_carry_node_timeouts() -> None:
    timeouts = {name: timeout for name, _, timeout in graph_module.STEPS}
    assert timeouts["draft_claims"] == 120.0
    assert timeouts["write_analysis"] == 150.0
    assert all(
        timeout is None
        for name, _, timeout in graph_module.STEPS
        if name not in {"draft_claims", "write_analysis"}
    )


@pytest.mark.anyio
async def test_forecast_returns_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            recorded["config"] = config
            recorded["context"] = context
            return {"answer": "The answer."}

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    # Act
    answer = await graph_module.forecast("Will it happen?")
    # Assert
    assert answer == "The answer."
    assert recorded["config"] is graph_module.NO_CHECKPOINTER_CONFIG
    assert isinstance(recorded["context"], ForecastRun)


@pytest.mark.anyio
async def test_the_wall_cap_names_the_step(monkeypatch: pytest.MonkeyPatch) -> None:
    record = {"cancelled": False}

    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            context.step = "Council voting, round 1 of 2"
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                record["cancelled"] = True
                raise
            return {"answer": "x"}

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    monkeypatch.setattr(
        graph_module,
        "LIMITS",
        dataclasses.replace(graph_module.LIMITS, wall_seconds=0.05),
    )
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await graph_module.forecast("Will it happen?")
    # Assert
    assert raised.value.status == 504
    assert str(raised.value).endswith("during this step: Council voting, round 1 of 2.")
    assert record["cancelled"] is True


@pytest.mark.anyio
async def test_an_inner_timeout_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise TimeoutError("inner")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(LLMInvocationError, match="The forecast failed."):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_a_step_timeout_is_a_research_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            context.step = "Drafting the claims"
            raise NodeTimeoutError("draft_claims", 90.5, kind="run", run_timeout=90.0)

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(ResearchLimitError) as raised:
        await graph_module.forecast("Will it happen?")
    assert raised.value.status == 504
    assert "90-second" in str(raised.value)
    assert "Drafting the claims" in str(raised.value)


@pytest.mark.anyio
async def test_a_real_step_timeout_is_a_research_limit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mutate(run: ResearchRun) -> None:
        run.searches = 2
        run.sources["https://a.example/1"] = Source("A", "https://a.example/1", "One.")
        run.sources["https://b.example/2"] = Source("B", "https://b.example/2", "Two.")

    class FakeAgent:
        def __init__(self, run: ResearchRun) -> None:
            self.run = run

        async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
            mutate(self.run)
            return {"messages": []}

    monkeypatch.setattr(
        research_node, "build_research_agent", lambda run: FakeAgent(run)
    )

    async def slow_claims(
        system: Any, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        await asyncio.sleep(1)
        raise AssertionError("the step should have timed out first")

    monkeypatch.setattr(draft_claims_node, "ainvoke_structured", slow_claims)
    steps = [
        (name, node, 0.05 if name == "draft_claims" else timeout)
        for name, node, timeout in graph_module.STEPS
    ]
    monkeypatch.setattr(graph_module, "STEPS", tuple(steps))
    # Act
    with pytest.raises(ResearchLimitError) as raised:
        await graph_module.forecast("Will it happen?")
    # Assert
    assert raised.value.status == 504
    assert "Drafting the claims" in str(raised.value)


@pytest.mark.anyio
async def test_a_pipeline_error_keeps_its_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise NoSourcesError("nothing readable")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(NoSourcesError):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_an_arbitrary_failure_is_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self, state: Any, *, config: Any = None, context: Any = None
        ) -> dict[str, Any]:
            raise RuntimeError("bug")

    monkeypatch.setattr(graph_module, "build_graph", lambda: FakeGraph())
    with pytest.raises(LLMInvocationError, match="The forecast failed."):
        await graph_module.forecast("Will it happen?")


@pytest.mark.anyio
async def test_a_forecast_runs_every_step_once_inside_a_checkpointed_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The research step: a fake agent that records two sources on two hosts.
    def mutate(run: ResearchRun) -> None:
        run.searches = 2
        run.sources["https://a.example/1"] = Source(
            "A article", "https://a.example/1", "Alpha one.\nAlpha two.\nAlpha three."
        )
        run.sources["https://b.example/2"] = Source(
            "B article", "https://b.example/2", "Beta one.\nBeta two.\nBeta three."
        )

    class FakeAgent:
        def __init__(self, run: ResearchRun) -> None:
            self.run = run

        async def ainvoke(self, agent_input: Any, *, config: Any = None) -> Any:
            mutate(self.run)
            return {"messages": []}

    monkeypatch.setattr(
        research_node, "build_research_agent", lambda run: FakeAgent(run)
    )

    # The two structured calls: claims, then the analysis.
    async def fake_claims(
        system: Any, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        return importlib.import_module("agents.deep_forecaster.models").DraftedClaims(
            claims=claims()
        )

    async def fake_analysis(
        system: Any, messages: Any, schema: Any, **kwargs: Any
    ) -> Any:
        return Analysis(
            overview="The council leans yes. [A](https://a.example/1)",
            claims=[
                ClaimDiscussion(claim=1, discussion="Alpha. [A](https://a.example/1)"),
                ClaimDiscussion(claim=2, discussion="Beta. [B](https://b.example/2)"),
            ],
        )

    monkeypatch.setattr(draft_claims_node, "ainvoke_structured", fake_claims)
    monkeypatch.setattr(write_analysis_node, "ainvoke_structured", fake_analysis)

    # The council: fakes keyed by model id, scripted per the plan's scenario.
    member_calls: list[tuple[str, int, str]] = []
    model_reads: list[str] = []
    scripted = {
        # Member 3's free model fails round 1; its fallback votes there.
        "nvidia/nemotron-3-ultra-550b-a55b:free": {"fail_first": True},
        # Member 7's free model fails round 2, and so does its fallback.
        "inclusionai/ling-3.0-flash-sante:free": {"fail_second": True},
        "inclusionai/ling-3.0-flash": {"always": True},
    }
    counters: dict[str, int] = {}

    class FakeModel:
        def __init__(self, model: str, max_retries: int) -> None:
            self.model = model
            self.max_retries = max_retries

        async def ainvoke(self, messages: Any) -> Any:
            counters[self.model] = counters.get(self.model, 0) + 1
            model_reads.append("\n".join(str(m.content) for m in messages))
            script = scripted.get(self.model)
            count = counters[self.model]
            if script is not None and (
                ("always" in script)
                or (script.get("fail_first") and count == 1)
                or (script.get("fail_second") and count >= 2)
            ):
                member_calls.append((self.model, self.max_retries, "failed"))
                raise RuntimeError("planned failure")
            member_calls.append((self.model, self.max_retries, "ok"))
            return ballot(["for", "unsure"])

    def fake_member_model(seat: Any, model: str, *, max_retries: int) -> FakeModel:
        return FakeModel(model, max_retries)

    monkeypatch.setattr(council_module, "member_model", fake_member_model)

    # The parent graph, with a saver, calls `forecast()` from a node.
    class ParentState(TypedDict):
        answer: str

    saver = InMemorySaver()

    async def parent_node(state: ParentState) -> dict[str, Any]:
        answer = await graph_module.forecast("Will it happen?")
        return {"answer": answer}

    builder: Any = StateGraph(ParentState, context_schema=ForecastRun)
    builder.add_node("forecast", parent_node)
    builder.add_edge(START, "forecast")
    builder.add_edge("forecast", END)
    parent = builder.compile(checkpointer=saver)

    labels: list[str] = []
    from agents.deep_forecaster.consts.progress import (
        CLAIMS_LABEL,
        RESEARCH_LABEL,
        ROUND_LABEL,
        VERIFY_LABEL,
        WRITE_LABEL,
    )

    expected_labels = [
        RESEARCH_LABEL,
        CLAIMS_LABEL,
        ROUND_LABEL.format(round=1),
        ROUND_LABEL.format(round=2),
        WRITE_LABEL,
        VERIFY_LABEL,
    ]

    # Act
    async for chunk in parent.astream(
        {"answer": ""},
        config={"configurable": {"thread_id": "t"}},
        context=ForecastRun(),
        stream_mode="custom",
        subgraphs=True,
    ):
        if isinstance(chunk[1], dict) and "label" in chunk[1]:
            labels.append(chunk[1]["label"])
    final = await parent.aget_state({"configurable": {"thread_id": "t"}})
    result = final.values
    answer_text = str(result["answer"])
    # Assert
    assert labels == expected_labels
    assert "### Claim 1: ACCEPTED" in answer_text
    assert "### Claim 2: UNRESOLVED" in answer_text
    assert "Members voting: 7 of 7." in answer_text
    assert (
        "Round 2: 1 of 7 kept their round-1 vote because they did not answer."
        in answer_text
    )
    assert (
        "Evidence: 2 sources read from 2 sites. The council voted on 3 passages "
        "quoted from 2 of them." in answer_text
    )
    assert "- Member 7 (round-1 vote):" in answer_text
    # 16 member calls: round 1 is 7 seats plus member 3's fallback; round 2 is
    # 6 answers plus member 7's free model and its fallback; 3 calls fail.
    assert len(member_calls) == 16
    assert len([call for call in member_calls if call[2] == "failed"]) == 3
    assert {call[0] for call in member_calls if call[2] == "failed"} == {
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "inclusionai/ling-3.0-flash-sante:free",
        "inclusionai/ling-3.0-flash",
    }
    # No member read the text of a paragraph no claim points at.
    assert not any("Alpha two." in read for read in model_reads)
    # The parent's saver holds no child checkpoint.
    namespaces: set[str] = set()
    async for checkpoint in saver.alist({"configurable": {"thread_id": "t"}}):
        namespaces.add(checkpoint.config["configurable"]["checkpoint_ns"])
    assert namespaces == {""}
