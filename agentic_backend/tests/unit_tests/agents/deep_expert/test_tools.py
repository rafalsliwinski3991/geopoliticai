"""Unit tests for `agents.deep_expert.tools`."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents.deep_expert.config import LIMITS
from agents.deep_expert.state import ResearchRun
from agents.expert.consts.sources import EXPERT_SOURCES
from frames import ProgressFrame
from models import Candidate, SearchUnavailableError, Source

tools_module: Any = __import__("importlib").import_module("agents.deep_expert.tools")

URL = "https://www.reuters.com/world/article"


async def call(tool: Any, args: dict[str, Any]) -> str:
    result: str = await tool.ainvoke(args)
    return result


def recorded_search(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    async def _search(query: str, policy: Any) -> list[Candidate]:
        calls.append((query, policy))
        return [Candidate(title="t", url=URL, domain="reuters.com")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _search)
    return calls


def recorded_fetch(monkeypatch: pytest.MonkeyPatch) -> list[list[Candidate]]:
    calls: list[list[Candidate]] = []

    async def _fetch(candidates: list[Candidate], policy: Any) -> list[Source]:
        calls.append(candidates)
        return [Source(title="t", url=URL, text="text")]

    monkeypatch.setattr(tools_module, "fetch_sources", _fetch)
    return calls


def fake_fetch(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    async def _call(*args: Any, **kwargs: Any) -> Any:
        return value

    monkeypatch.setattr(tools_module, "fetch_sources", _call)


@pytest.mark.anyio
async def test_a_search_returns_lines_and_spends_one_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    result = await call(search_sources, {"query": "EU carbon border tax"})

    # Assert
    assert result.endswith("Searches left: 4.")
    assert run.searches == 1
    assert URL in run.candidates
    assert events_list == [
        ProgressFrame(node="deep_expert", label="Searching sources (1 of 5)...")
    ]
    assert calls == [("EU carbon border tax", EXPERT_SOURCES)]


@pytest.mark.anyio
async def test_a_blank_query_refuses_without_spending_a_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    blank = await call(search_sources, {"query": "   "})
    empty = await call(search_sources, {"query": ""})

    # Assert
    assert blank == tools_module.EMPTY_QUERY_MESSAGE
    assert empty == tools_module.EMPTY_QUERY_MESSAGE
    assert calls == []
    assert run.searches == 0
    assert events_list == []


@pytest.mark.anyio
async def test_a_noisy_query_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    calls = recorded_search(monkeypatch)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    await call(search_sources, {"query": "  EU   carbon tax  "})

    # Assert
    assert calls == [("EU carbon tax", EXPERT_SOURCES)]


@pytest.mark.anyio
async def test_the_search_cap_is_a_soft_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls = recorded_search(monkeypatch)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    for _ in range(LIMITS.max_searches):
        await call(search_sources, {"query": "q"})
    sixteenth = await call(search_sources, {"query": "q"})

    # Assert
    assert sixteenth == tools_module.NO_SEARCHES_LEFT_MESSAGE
    assert calls == [("q", EXPERT_SOURCES)] * LIMITS.max_searches
    assert run.searches == LIMITS.max_searches
    assert events_list[-1].label == "Searching sources (5 of 5)..."


@pytest.mark.anyio
async def test_an_empty_search_returns_the_no_results_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: the search is spent, no candidates are stored, and the footer
    # still reports the remaining budget.
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    calls: list[str] = []

    async def _empty(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", _empty)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    result = await call(search_sources, {"query": "nothing matches"})

    # Assert
    assert result == "No approved results for that query.\n\nSearches left: 4."
    assert calls == ["nothing matches"]
    assert run.searches == 1
    assert run.candidates == {}
    assert [event.label for event in events_list] == ["Searching sources (1 of 5)..."]


@pytest.mark.anyio
async def test_a_repeated_url_keeps_the_first_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: the second hit of the same URL carries a different title, but
    # the budget keeps the first seen (keep-first setdefault merge).
    run = ResearchRun(writer=(lambda e: None))
    calls: list[str] = []

    async def _two_hits(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        if len(calls) == 1:
            return [Candidate(title="first", url=URL, domain="reuters.com")]
        return [Candidate(title="second", url=URL, domain="reuters.com")]

    monkeypatch.setattr(tools_module, "search_allowlisted", _two_hits)
    (search_sources, _) = tools_module.build_tools(run)

    # Act
    await call(search_sources, {"query": "one"})
    await call(search_sources, {"query": "two"})

    # Assert
    assert run.candidates[URL].title == "first"


@pytest.mark.anyio
async def test_a_concurrent_read_fetches_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two same-URL reads started together share one in-flight fetch.

    The per-URL lock (`ResearchRun.lock_for`) serializes them: the loser finds
    the source cached. Without the lock both miss the cache before either
    stores, and the page is fetched twice (review thread, #129 c4142559750).
    """
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fetches = recorded_fetch(monkeypatch)
    (search_sources, read_source) = tools_module.build_tools(run)
    await call(search_sources, {"query": "q"})

    # Act
    first, second = await asyncio.gather(
        call(read_source, {"url": URL}),
        call(read_source, {"url": URL}),
    )

    # Assert
    assert first.startswith("--- SOURCE ---")
    assert second.startswith("--- SOURCE ---")
    assert len(fetches) == 1


@pytest.mark.anyio
async def test_a_search_outage_is_a_hard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))

    async def _boom(query: str, policy: Any) -> list[Candidate]:
        raise SearchUnavailableError("brave down")

    monkeypatch.setattr(tools_module, "search_allowlisted", _boom)
    (search_sources, _) = tools_module.build_tools(run)

    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await call(search_sources, {"query": "q"})
    assert run.searches == 1


@pytest.mark.anyio
async def test_read_source_refuses_an_unknown_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    fetches = recorded_fetch(monkeypatch)
    (_, read_source) = tools_module.build_tools(run)

    # Act
    result = await call(read_source, {"url": "https://unsearched.example/1"})

    # Assert
    assert result == tools_module.UNKNOWN_URL_MESSAGE
    assert fetches == []


@pytest.mark.anyio
async def test_read_source_returns_the_requested_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    events_list: list[ProgressFrame] = []
    run = ResearchRun(writer=events_list.append)
    recorded_search(monkeypatch)

    async def _redirect_fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url="https://other.example/redirected", text="text")]

    monkeypatch.setattr(tools_module, "fetch_sources", _redirect_fetch)
    (search_sources, read_source) = tools_module.build_tools(run)
    await call(search_sources, {"query": "q"})

    # Act
    result = await call(read_source, {"url": URL})

    # Assert
    assert result.startswith("--- SOURCE ---")
    assert f"URL: {URL}" in result
    # Keyed by the URL the model asked for, even though the fetch redirected.
    assert URL in run.sources
    assert run.sources[URL].url == "https://other.example/redirected"
    assert events_list[-1].label == "Reading sources (1 so far)..."


@pytest.mark.anyio
async def test_a_second_read_does_not_fetch_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fetches = recorded_fetch(monkeypatch)
    (search_sources, read_source) = tools_module.build_tools(run)
    await call(search_sources, {"query": "q"})

    # Act
    await call(read_source, {"url": URL})
    second = await call(read_source, {"url": URL})

    # Assert
    assert second.startswith("--- SOURCE ---")
    assert len(fetches) == 1


@pytest.mark.anyio
async def test_an_unreadable_page_returns_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run = ResearchRun(writer=(lambda e: None))
    recorded_search(monkeypatch)
    fake_fetch(monkeypatch, [])
    (search_sources, read_source) = tools_module.build_tools(run)
    await call(search_sources, {"query": "q"})

    # Act
    result = await call(read_source, {"url": URL})

    # Assert
    assert result == tools_module.UNREADABLE_MESSAGE
    assert URL not in run.sources


@pytest.mark.anyio
async def test_two_runs_do_not_share_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    recorded_search(monkeypatch)
    first = ResearchRun(writer=(lambda e: None))
    second = ResearchRun(writer=(lambda e: None))
    (first_search, _) = tools_module.build_tools(first)
    (second_search, _) = tools_module.build_tools(second)

    # Act
    await call(first_search, {"query": "q"})

    # Assert
    assert first.searches == 1
    assert second.searches == 0
