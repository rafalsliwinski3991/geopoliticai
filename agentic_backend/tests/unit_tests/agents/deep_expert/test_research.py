"""Unit tests for `agents.deep_expert.research`."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from agents.deep_expert.config import ResearchLimits
from agents.deep_expert.prompts import DEEP_ANSWER_RUBRIC
from agents.deep_expert.state import ResearchRun
from models import (
    LLMInvocationError,
    NoSourcesError,
    ResearchLimitError,
    SearchUnavailableError,
    Source,
)

research_module: Any = importlib.import_module("agents.deep_expert.research")

DEEP_ANSWER = "Deep answer [a](https://reuters.com/x)."


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
    events: list[dict[str, Any]] = []
    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], cited_run())

    def _build_graph(run: ResearchRun) -> Any:
        spy.bind_run(run)
        return spy

    monkeypatch.setattr(research_module, "build_graph", _build_graph)

    # Act
    deep_answer = await research_module.research("q", events.append)

    # Assert
    assert deep_answer == DEEP_ANSWER
    assert events[0] == research_module.PLANNING_PROGRESS


@pytest.mark.anyio
async def test_max_iterations_reached_ships_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], verdict_run("max_iterations_reached"))
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    deep_answer = await research_module.research("q", lambda e: None)

    # Assert
    assert deep_answer == DEEP_ANSWER


@pytest.mark.anyio
@pytest.mark.parametrize("verdict", ["grader_error", "failed"])
async def test_a_failed_grader_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch, verdict: str
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], verdict_run(verdict))
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="grader"):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_no_verdict_at_all_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], sources_only())
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_no_sources_read_is_no_sources_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy(
        [AIMessage(DEEP_ANSWER)], lambda run: run.verdicts.append("satisfied")
    )
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(NoSourcesError):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_sources_read_but_none_cited_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage("An uncited answer.")], cited_run())
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="cited"):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_an_empty_answer_is_a_hard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([], cited_run())
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_the_answer_is_found_past_a_rubric_human_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    messages: list[Any] = [
        AIMessage(DEEP_ANSWER),
        HumanMessage("revise"),
    ]
    spy = _GraphSpy(messages, cited_run())
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    deep_answer = await research_module.research("q", lambda e: None)

    # Assert
    assert deep_answer == DEEP_ANSWER


@pytest.mark.anyio
async def test_a_search_outage_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = SearchUnavailableError("brave down")
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await research_module.research("q", lambda e: None)


@pytest.mark.anyio
async def test_an_arbitrary_failure_becomes_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([])
    spy.fail_with = ValueError("boom")
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await research_module.research("q", lambda e: None)


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

    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], five_searches)
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))
    # Act
    await research_module.research("q", lambda e: None)
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
    monkeypatch.setattr(research_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _GraphSpy([])
    spy.sleep_for = 1.0

    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))
    # Act
    with pytest.raises(ResearchLimitError, match="0.01-second"):
        await research_module.research("q", lambda e: None)
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
    monkeypatch.setattr(research_module, "LIMITS", ResearchLimits(wall_seconds=0.01))
    spy = _GraphSpy([])
    spy.sleep_for = 1.0
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    run = research_module.research("q", lambda e: None)
    # Assert
    with pytest.raises(ResearchLimitError, match="0.01-second"):
        await run


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
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    call = research_module.research("q", lambda e: None)
    # Assert
    with pytest.raises(LLMInvocationError):
        await call


@pytest.mark.anyio
async def test_the_agent_receives_the_rubric_and_the_no_checkpoint_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    spy = _GraphSpy([AIMessage(DEEP_ANSWER)], cited_run())
    monkeypatch.setattr(research_module, "build_graph", lambda run: spy.bind_run(run))

    # Act
    await research_module.research("the question", lambda e: None)

    # Assert
    state, config = spy.invocations[0]
    assert [type(m).__name__ for m in state["messages"]] == ["HumanMessage"]
    assert state["messages"][0].content == "the question"
    assert state["rubric"] == DEEP_ANSWER_RUBRIC
    graph_module: Any = importlib.import_module("agents.deep_expert.graph")
    assert config == {"configurable": {graph_module.CONFIG_KEY_CHECKPOINTER: None}}
