"""Unit tests for `evals.deep_expert_live`; no Brave search or model call happens."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any
from unittest.mock import patch

import pytest

from agents.expert.consts.sources import EXPERT_SOURCES
from evals.deep_expert_live import run_deep_expert_live
from models import Candidate, Source, SourcePolicy

tools_module: Any = importlib.import_module("agents.deep_expert.tools")
search_node: Any = importlib.import_module("agents.expert.nodes.search_and_fetch")

PAGE_A = Source(title="A", url="https://news.example/a", text="a text")
PAGE_B = Source(title="B", url="https://news.example/b", text="b text")


async def live_fetch(
    candidates: Sequence[Candidate], policy: SourcePolicy
) -> list[Source]:
    """Stand in for `search.fetch_sources`: return the page scripted for each URL."""
    pages = {PAGE_A.url: PAGE_A, PAGE_B.url: PAGE_B}
    return [pages[candidate.url] for candidate in candidates]


async def deep_research(query: str, writer: Any) -> str:
    """Stand in for the deep run: read page A then page B through the deep tools."""
    for page in (PAGE_A, PAGE_B):
        candidate = Candidate(title=page.title, url=page.url, domain="news.example")
        await tools_module.fetch_sources([candidate], EXPERT_SOURCES)
    return "The deep answer."


async def graded_deep_research(query: str, writer: Any) -> str:
    """Stand in for the deep run: read page A, then let the grader revise once and be satisfied."""
    research_module: Any = importlib.import_module("agents.deep_expert.graph")
    candidate = Candidate(title=PAGE_A.title, url=PAGE_A.url, domain="news.example")
    await tools_module.fetch_sources([candidate], EXPERT_SOURCES)
    run = research_module.ResearchRun(writer=writer)
    run.verdicts.extend(["needs_revision", "satisfied"])
    return "The deep answer."


class RecordingExpertGraph:
    """A stand-in for the expert's graph: searches and fetches as the real node does, and records the URLs."""

    def __init__(self) -> None:
        self.fetched_urls: list[str] = []

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        candidates = await search_node.search_allowlisted("q", EXPERT_SOURCES)
        sources = await search_node.fetch_sources(candidates, EXPERT_SOURCES)
        self.fetched_urls = [source.url for source in sources]
        return {"answer": "The baseline.", "sources": sources}


@pytest.mark.anyio
async def test_the_baseline_expert_reads_exactly_the_pages_the_deep_run_read() -> None:
    """Depth is only comparable when both answers come from the same pages; another search would measure luck."""
    # Arrange
    expert_graph = RecordingExpertGraph()

    # Act
    with (
        patch("services.page_reader.fetch_sources", live_fetch),
        patch("agents.deep_expert.research", deep_research),
        patch("agents.expert.graph", expert_graph),
    ):
        output = await run_deep_expert_live({"query": "q"})

    # Assert
    assert expert_graph.fetched_urls == [PAGE_A.url, PAGE_B.url]
    assert [source["url"] for source in output["sources"]] == [PAGE_A.url, PAGE_B.url]
    assert output["answer"] == "The deep answer."
    assert output["baseline_answer"] == "The baseline."


class FailingExpertGraph:
    """A stand-in for the expert's graph whose run fails the way a refused model call does."""

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("the model refused")


@pytest.mark.anyio
async def test_a_failed_baseline_names_its_step_and_keeps_the_cause() -> None:
    """The row's cause must say the deep run finished and the baseline failed, not just what broke."""
    # Arrange
    expert_graph = FailingExpertGraph()

    # Act + Assert
    with (
        patch("services.page_reader.fetch_sources", live_fetch),
        patch("agents.deep_expert.research", deep_research),
        patch("agents.expert.graph", expert_graph),
        pytest.raises(
            RuntimeError, match="^baseline: ValueError: the model refused$"
        ) as raised,
    ):
        await run_deep_expert_live({"query": "q"})
    assert isinstance(raised.value.__cause__, ValueError)


@pytest.mark.anyio
async def test_the_live_eval_returns_the_grader_verdicts() -> None:
    """The grader_satisfied judge reads the verdicts from the row; without them it cannot tell a cap from a pass."""
    # Arrange
    expert_graph = RecordingExpertGraph()

    # Act
    with (
        patch("services.page_reader.fetch_sources", live_fetch),
        patch("agents.deep_expert.research", graded_deep_research),
        patch("agents.expert.graph", expert_graph),
    ):
        output = await run_deep_expert_live({"query": "q"})

    # Assert
    assert output["grader_verdicts"] == ["needs_revision", "satisfied"]
