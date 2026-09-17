"""Unit tests for `evals.helpers.graph`."""

from __future__ import annotations

import importlib
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from evals.helpers.graph import load_sources, pending_pause, recorded_sources
from models import Source, SourcePolicy

search_node: Any = importlib.import_module("agents.expert.nodes.search_and_fetch")

POLICY = SourcePolicy(
    allowed_domains=(),
    batches=(),
    deferred_domains=frozenset(),
    max_per_domain=0,
    min_source_chars=0,
    max_source_chars=0,
)


def test_load_sources_builds_source_objects() -> None:
    # Act
    sources = load_sources([{"title": "t", "url": "u", "text": "x"}])

    # Assert
    assert sources == [Source(title="t", url="u", text="x")]


@pytest.mark.anyio
async def test_recorded_sources_patches_expert_retrieval() -> None:
    # Arrange
    recorded = [Source(title="t", url="https://news.example/a", text="text")]
    original_search = search_node.search_allowlisted
    original_fetch = search_node.fetch_sources

    # Act
    with recorded_sources(lambda: recorded):
        candidates = await search_node.search_allowlisted("q", POLICY)
        fetched = await search_node.fetch_sources([], POLICY)

    # Assert
    assert [(c.title, c.url, c.domain) for c in candidates] == [
        ("t", "https://news.example/a", "recorded")
    ]
    assert fetched == recorded
    assert search_node.search_allowlisted is original_search
    assert search_node.fetch_sources is original_fetch


@pytest.mark.anyio
async def test_recorded_sources_raises_when_no_sources_recorded() -> None:
    # Act + Assert
    with (
        recorded_sources(lambda: None),
        pytest.raises(RuntimeError, match="no recorded sources"),
    ):
        await search_node.search_allowlisted("q", POLICY)
    with (
        recorded_sources(lambda: None),
        pytest.raises(RuntimeError, match="no recorded sources"),
    ):
        await search_node.fetch_sources([], POLICY)


class _PauseState(TypedDict):
    value: str


def _pause_graph(value: Any) -> Any:
    def _node(state: _PauseState) -> dict[str, str]:
        result = interrupt(value)
        return {"value": str(result)}

    builder = StateGraph(_PauseState)
    builder.add_node("pause", _node)
    builder.add_edge(START, "pause")
    builder.add_edge("pause", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.anyio
async def test_pending_pause_returns_dict_interrupt_value() -> None:
    # Arrange
    graph = _pause_graph({"outline": ["A"]})
    config = {"configurable": {"thread_id": "t1"}}
    await graph.ainvoke({}, config)

    # Act
    pause = await pending_pause(graph, config)

    # Assert
    assert pause == {"outline": ["A"]}


@pytest.mark.anyio
async def test_pending_pause_returns_none_after_resume() -> None:
    # Arrange
    graph = _pause_graph({"outline": ["A"]})
    config = {"configurable": {"thread_id": "t2"}}
    await graph.ainvoke({}, config)

    # Act
    await graph.ainvoke(Command(resume="go"), config)
    pause = await pending_pause(graph, config)

    # Assert
    assert pause is None


@pytest.mark.anyio
async def test_pending_pause_wraps_non_dict_interrupt_value() -> None:
    # Arrange
    graph = _pause_graph("paused!")
    config = {"configurable": {"thread_id": "t3"}}
    await graph.ainvoke({}, config)

    # Act
    pause = await pending_pause(graph, config)

    # Assert
    assert pause == {"outline": [], "notice": "paused!"}
