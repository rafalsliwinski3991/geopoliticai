"""Unit tests for `agents.deep_forecaster.tools`."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest
from langchain_core.tools import BaseTool
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import agents.deep_forecaster.tools as tools_module
from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.consts.forecasters import FORECASTERS_BY_ID
from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED
from agents.deep_forecaster.state import ResearchRun
from agents.deep_forecaster.tools import (
    EMPTY_QUERY_MESSAGE,
    EMPTY_QUESTION_MESSAGE,
    NO_RESULTS_MESSAGE,
    NO_SEARCHES_LEFT_MESSAGE,
    NO_SOURCES_LEFT_MESSAGE,
    NO_VIDEOS_LEFT_MESSAGE,
    NOT_A_VIDEO_MESSAGE,
    SEARCH_FAILED_MESSAGE,
    UNKNOWN_FORECASTER_MESSAGE,
    UNKNOWN_URL_MESSAGE,
    UNREADABLE_MESSAGE,
    VIDEO_ASKED_AGAIN_MESSAGE,
    VIDEO_OFF_TOPIC_MESSAGE,
    VIDEO_UNAVAILABLE_MESSAGE,
    VIDEO_URL_MESSAGE,
    build_tools,
)
from agents.deep_forecaster.video import VideoUnavailableError
from models import Candidate, Source
from shared.errors import SearchUnavailableError
from shared.frames import ProgressFrame


def _candidate(url: str, domain: str | None = None, title: str = "t") -> Candidate:
    from urllib.parse import urlparse

    return Candidate(
        title,
        url,
        domain or urlparse(url).netloc.removeprefix("www.").removeprefix("m."),
    )


def _run(events: list[object]) -> ResearchRun:
    return ResearchRun(writer=events.append)


def _tools(run: ResearchRun) -> dict[str, BaseTool]:
    search, read, ask = build_tools(run)
    return {"search": search, "read": read, "ask": ask}


@pytest.fixture
def events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def run(events: list[object]) -> ResearchRun:
    return _run(events)


@pytest.fixture
def tools(run: ResearchRun) -> dict[str, BaseTool]:
    return _tools(run)


@pytest.mark.anyio
async def test_a_search_is_narrowed_to_one_forecaster(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    calls: list[tuple[str, Any]] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append((query, policy))
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["Russia China"]})
    # Assert
    assert calls == [("Gabuev Russia China", calls[0][1])]
    assert calls[0][1].allowed_domains == ("carnegieendowment.org",)
    assert calls[0][1].batches == (("carnegieendowment.org",),)
    assert run.searches == 1


@pytest.mark.anyio
async def test_a_site_operator_in_the_query_is_dropped(
    tools: dict[str, BaseTool], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke(
        {
            "forecaster": "gabuev",
            "queries": ["site:kcl.ac.uk Russia SITE:x.com China -site:y.org"],
        }
    )
    # Assert
    assert calls == ["Gabuev Russia China"]


@pytest.mark.anyio
async def test_a_query_of_only_site_operators_spends_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("Brave must not be called")

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["site:kcl.ac.uk"]}
    )
    # Assert
    assert result == EMPTY_QUERY_MESSAGE
    assert run.searches == 0


@pytest.mark.anyio
async def test_an_unknown_forecaster_spends_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("Brave must not be called")

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke({"forecaster": "nobody", "queries": ["q"]})
    # Assert
    assert result == UNKNOWN_FORECASTER_MESSAGE.format(ids=", ".join(FORECASTERS_BY_ID))
    assert run.searches == 0


@pytest.mark.anyio
async def test_a_blank_query_spends_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("Brave must not be called")

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["   "]})
    # Assert
    assert result == EMPTY_QUERY_MESSAGE
    assert run.searches == 0


@pytest.mark.anyio
async def test_the_search_cap_is_a_soft_stop(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    tools = _tools(run)
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    import agents.deep_forecaster.config as config

    monkeypatch.setattr(
        tools_module, "LIMITS", dataclasses.replace(config.LIMITS, max_searches=1)
    )
    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["q"]})
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["q again"]}
    )
    # Assert
    assert result == NO_SEARCHES_LEFT_MESSAGE
    assert len(calls) == 1


@pytest.mark.anyio
async def test_read_sources_refuses_an_unknown_url(
    tools: dict[str, BaseTool], run: ResearchRun
) -> None:
    # Arrange
    unknown = "https://carnegieendowment.org/x"
    # Act
    result = await tools["read"].ainvoke({"urls": [unknown]})
    # Assert
    assert result == f"URL: {unknown}\n{UNKNOWN_URL_MESSAGE}"


@pytest.mark.anyio
async def test_read_sources_refuses_a_video(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise AssertionError("A video must not be fetched")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [url]})
    # Assert
    assert result == f"URL: {url}\n{VIDEO_URL_MESSAGE}"


@pytest.mark.anyio
async def test_read_sources_shows_the_byline_and_the_asked_url(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    asked = "https://carnegieendowment.org/x"
    fetched_url = "https://carnegieendowment.org/x-final"
    run.candidates[asked] = _candidate(asked)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return [
            Source(
                title="t",
                url=fetched_url,
                text="article text",
                author="Alexander Gabuev",
            )
        ]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [asked]})
    # Assert
    assert "Byline: Alexander Gabuev" in result
    assert asked in result
    assert run.sources[asked].url == asked


@pytest.mark.anyio
async def test_the_source_cap_is_a_soft_stop(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    tools = _tools(run)
    import agents.deep_forecaster.config as config
    from agents.deep_forecaster import state as state_module

    small = dataclasses.replace(config.LIMITS, max_sources=0)
    monkeypatch.setattr(tools_module, "LIMITS", small)
    monkeypatch.setattr(state_module, "LIMITS", small)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise AssertionError("No room: nothing must be fetched")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    url = "https://carnegieendowment.org/x"
    run.candidates[url] = _candidate(url)
    # Act
    result = await tools["read"].ainvoke({"urls": [url]})
    # Assert
    assert result == f"URL: {url}\n{NO_SOURCES_LEFT_MESSAGE}"
    assert run.reserved == 0


@pytest.mark.anyio
async def test_a_concurrent_read_fetches_once(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    search, read, ask = build_tools(run)
    url = "https://carnegieendowment.org/x"
    run.candidates[url] = _candidate(url)
    calls: list[int] = []

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        calls.append(1)
        await asyncio.sleep(0.05)
        return [Source(title="t", url=url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    results = await asyncio.gather(*[read.ainvoke({"urls": [url]}) for _ in range(3)])
    # Assert
    assert len(calls) == 1
    assert all(result == results[0] for result in results)
    assert len(run.sources) == 1


@pytest.mark.anyio
async def test_parallel_reads_never_overshoot_the_source_cap(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    search, read, ask = build_tools(run)
    import agents.deep_forecaster.config as config
    from agents.deep_forecaster import state as state_module

    small = dataclasses.replace(config.LIMITS, max_sources=2)
    monkeypatch.setattr(tools_module, "LIMITS", small)
    monkeypatch.setattr(state_module, "LIMITS", small)
    urls = [f"https://carnegieendowment.org/{n}" for n in range(5)]
    # Act
    for url in urls:
        run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        await asyncio.sleep(0.05)
        candidate = candidates[0]
        return [Source(title="t", url=candidate.url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    results = await asyncio.gather(*[read.ainvoke({"urls": [url]}) for url in urls])
    # Assert
    assert len(run.sources) == 2
    refusals = [result for result in results if NO_SOURCES_LEFT_MESSAGE in result]
    assert len(refusals) == 3
    assert run.reserved == 0


@pytest.mark.anyio
async def test_a_failed_search_is_a_message(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        raise SearchUnavailableError("Brave is down")

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["q"]})
    # Assert
    left = LIMITS.max_searches - 1
    assert result == f"Query: q\n{SEARCH_FAILED_MESSAGE}\n\nSearches left: {left}."
    assert run.searches == 1 and run.failed_searches == 1


@pytest.mark.anyio
async def test_searches_run_at_most_the_concurrency_cap_at_once(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    search, read, ask = build_tools(run)
    peak = 0
    current = 0

    async def fake(query: str, policy: Any) -> list[Candidate]:
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await asyncio.gather(
        *[
            search.ainvoke({"forecaster": "gabuev", "queries": [f"q{n}"]})
            for n in range(2 * LIMITS.max_search_concurrency)
        ]
    )
    # Assert
    assert peak == LIMITS.max_search_concurrency


@pytest.mark.anyio
async def test_several_queries_run_in_one_call(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call carries the two to five queries the scout wrote, and every
    query runs as its own Brave request, so one scout turn does one batch of
    work instead of one search."""
    # Arrange
    peak = 0
    current = 0
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        nonlocal peak, current
        calls.append(query)
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["q1", "q2", "q3"]}
    )
    # Assert
    assert len(calls) == 3
    assert peak == 3
    assert run.searches == 3
    assert result.count("Query: ") == 3


@pytest.mark.anyio
async def test_a_batch_stops_at_the_search_cap(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared budget bounds every call: with two searches left, a
    four-query batch runs two and names the ones it did not run, so a single
    scout cannot spend the parallel scouts' searches."""
    # Arrange
    tools = _tools(run)
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    import agents.deep_forecaster.config as config

    monkeypatch.setattr(
        tools_module, "LIMITS", dataclasses.replace(config.LIMITS, max_searches=2)
    )
    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["q1", "q2", "q3", "q4"]}
    )
    # Assert
    assert len(calls) == 2
    assert result.endswith("Not run (no searches left): q3; q4\n\nSearches left: 0.")


@pytest.mark.anyio
async def test_only_the_first_five_queries_run(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": [f"q{n}" for n in range(1, 8)]}
    )
    # Assert
    assert len(calls) == 5
    assert run.searches == 5
    assert "Not run (at most 5 queries per call): q6; q7" in result


@pytest.mark.anyio
async def test_a_repeated_query_spends_one_search(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A query repeated in one call is dropped: a repeated one would spend a
    search on results the scout already has."""
    # Arrange
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["q", "q"]})
    # Assert
    assert len(calls) == 1
    assert run.searches == 1


@pytest.mark.anyio
async def test_parallel_batches_never_overshoot_the_search_cap(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batch's searches are spent before any request awaits, so two
    scouts calling together cannot together take more searches than are left."""
    # Arrange
    search, read, ask = build_tools(run)
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        await asyncio.sleep(0.05)
        return []

    import agents.deep_forecaster.config as config

    monkeypatch.setattr(
        tools_module, "LIMITS", dataclasses.replace(config.LIMITS, max_searches=3)
    )
    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await asyncio.gather(
        search.ainvoke({"forecaster": "gabuev", "queries": ["a1", "a2"]}),
        search.ainvoke({"forecaster": "gabuev", "queries": ["b1", "b2"]}),
    )
    # Assert
    assert len(calls) == 3
    assert run.searches == 3


@pytest.mark.anyio
async def test_a_search_records_its_forecaster_and_empty_results(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch search records which forecaster it searched, so the
    `forecast_research` span can say whose writing was collected, and a
    search that found nothing is counted apart from a failed one."""

    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["q"]})
    # Assert
    assert run.forecasters_searched == {"gabuev"}
    assert run.empty_searches == 1


@pytest.mark.anyio
async def test_read_sources_unreadable_page_says_so_without_spending(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://carnegieendowment.org/paywalled"
    run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return []

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [url]})
    # Assert
    assert result == f"URL: {url}\n{UNREADABLE_MESSAGE}"
    assert run.sources == {}
    assert run.reserved == 0
    assert run.unreadable_pages == 1


@pytest.mark.anyio
async def test_several_pages_are_read_in_one_call(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One call reads up to five articles together, so a scout turns one
    round trip into a batch of reads."""
    # Arrange
    urls = [f"https://carnegieendowment.org/{n}" for n in range(1, 4)]
    for url in urls:
        run.candidates[url] = _candidate(url)
    peak = 0
    current = 0
    fetches: list[str] = []

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        nonlocal peak, current
        fetches.append(candidates[0].url)
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": urls})
    # Assert
    assert len(fetches) == 3
    assert peak == 3
    assert len(run.sources) == 3
    assert result.count("--- SOURCE ---") == 3


@pytest.mark.anyio
async def test_a_full_batch_read_stays_under_the_eviction_threshold(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deepagents evicts a tool result past 80,000 characters, so a full
    batch of five full pages must arrive cut — while every page stays whole
    in `run.sources` for the drafter and the writer."""
    # Arrange
    page = "w" * 20_000
    urls = [f"https://carnegieendowment.org/{n}" for n in range(5)]
    for url in urls:
        run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=candidates[0].url, text=page)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": urls})
    # Assert
    assert len(result) < 80_000
    assert (
        result.count(
            "[First 14,000 of 20,000 characters shown; the whole page is recorded.]"
        )
        == 5
    )
    assert all(len(source.text) == 20_000 for source in run.sources.values())


@pytest.mark.anyio
async def test_a_batch_read_stops_at_the_page_cap(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    tools = _tools(run)
    import agents.deep_forecaster.config as config
    from agents.deep_forecaster import state as state_module

    small = dataclasses.replace(config.LIMITS, max_sources=2)
    monkeypatch.setattr(tools_module, "LIMITS", small)
    monkeypatch.setattr(state_module, "LIMITS", small)
    urls = [f"https://carnegieendowment.org/{n}" for n in range(3)]
    for url in urls:
        run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        await asyncio.sleep(0.05)
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": urls})
    # Assert
    assert len(run.sources) == 2
    assert result.endswith(f"URL: {urls[2]}\n{NO_SOURCES_LEFT_MESSAGE}")


@pytest.mark.anyio
async def test_one_bad_url_does_not_block_the_others(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    good = "https://carnegieendowment.org/good"
    unknown = "https://carnegieendowment.org/never-searched"
    run.candidates[good] = _candidate(good)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [unknown, good]})
    # Assert
    assert result.startswith(f"URL: {unknown}\n{UNKNOWN_URL_MESSAGE}")
    assert "--- SOURCE ---" in result
    assert len(run.sources) == 1
    assert run.sources[good].url == good


@pytest.mark.anyio
async def test_a_url_repeated_in_a_batch_is_fetched_once(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://carnegieendowment.org/x"
    run.candidates[url] = _candidate(url)
    fetches: list[str] = []

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        fetches.append(candidates[0].url)
        await asyncio.sleep(0.05)
        return [Source(title="t", url=url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [url, url]})
    # Assert
    assert fetches == [url]
    assert len(run.sources) == 1
    assert result.count("--- SOURCE ---") == 1


@pytest.mark.anyio
async def test_only_the_first_five_urls_are_read(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    urls = [f"https://carnegieendowment.org/{n}" for n in range(7)]
    for url in urls:
        run.candidates[url] = _candidate(url)
    fetches: list[str] = []

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        fetches.append(candidates[0].url)
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": urls})
    # Assert
    assert len(fetches) == 5
    assert len(run.sources) == 5
    assert f"Not read (at most 5 URLs per call): {urls[5]}; {urls[6]}" in result


@pytest.mark.anyio
async def test_an_empty_url_list_reads_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise AssertionError("Nothing to read")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": []})
    # Assert
    assert result == "No URLs were given. Pass URLs `search_forecaster` returned."
    assert run.sources == {}


@pytest.mark.anyio
async def test_ask_video_blank_question_spends_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        raise AssertionError("Gemini must not be called")

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "   "})
    # Assert
    assert result == EMPTY_QUESTION_MESSAGE
    assert run.videos == 0
    assert run.video_questions == {}


@pytest.mark.anyio
async def test_ask_video_mangled_video_id_refuses_to_cite_a_different_url(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange: the id decodes with extra query text, so the canonical URL must not be built from it.
    url = "https://www.youtube.com/watch?v=abc%26list%3DX"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        raise AssertionError("Gemini must not be called")

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result == NOT_A_VIDEO_MESSAGE
    assert run.videos == 0


@pytest.mark.anyio
async def test_ask_video_reask_with_a_different_question_names_the_old_one(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com", title="A talk")

    async def fake(video: str, question: str, store: Any = None) -> str:
        return "Notes " * 10

    monkeypatch.setattr(tools_module, "watch_video", fake)
    await tools["ask"].ainvoke({"url": url, "question": "first"})
    # Act: the same video, a new question, with no new video budget spent.
    result = await tools["ask"].ainvoke({"url": url, "question": "second"})
    # Assert
    assert result == VIDEO_ASKED_AGAIN_MESSAGE.format(question="first")
    assert run.videos == 1
    assert len(run.sources) == 1


@pytest.mark.anyio
async def test_ask_video_refuses_a_non_video(
    tools: dict[str, BaseTool], run: ResearchRun
) -> None:
    # Act
    result = await tools["ask"].ainvoke(
        {"url": "https://carnegieendowment.org/x", "question": "q"}
    )
    # Assert
    assert result == NOT_A_VIDEO_MESSAGE


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@KrzysztofWojczal",
        "https://www.youtube.com/shorts/abc",
        "https://www.youtube.com/playlist?list=PL1",
    ],
)
async def test_ask_video_refuses_a_channel_or_a_short_without_spending(
    url: str,
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        raise AssertionError("Gemini must not be called")

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result == NOT_A_VIDEO_MESSAGE
    assert run.videos == 0


@pytest.mark.anyio
async def test_ask_video_sends_one_canonical_url_per_video(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    first = "https://m.youtube.com/watch?v=abcdefghijk"
    second = "https://youtube.com/watch?v=abcdefghijk&t=30s"
    run.candidates[first] = _candidate(first, domain="youtube.com", title="A talk")
    run.candidates[second] = _candidate(second, domain="youtube.com", title="A talk")
    seen: list[str] = []

    async def fake(video: str, question: str, store: Any = None) -> str:
        seen.append(video)
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    await tools["ask"].ainvoke({"url": first, "question": "q"})
    canonical = "https://www.youtube.com/watch?v=abcdefghijk"
    # Assert
    assert seen == [canonical]
    assert run.sources[canonical].url == canonical
    await tools["ask"].ainvoke({"url": second, "question": "q"})
    assert seen == [canonical]
    assert run.videos == 1


@pytest.mark.anyio
async def test_ask_video_records_gemini_notes(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com", title="A talk")
    seen: list[str] = []

    async def fake(video: str, question: str, store: Any = None) -> str:
        seen.append(video)
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    stored = run.sources["https://www.youtube.com/watch?v=abcdefghijk"]
    # Assert
    assert stored.title == "Gemini's notes on the video: A talk"
    assert stored.author == ""
    assert "Notes" in result
    await tools["ask"].ainvoke({"url": url, "question": "q"})
    assert seen == [url]


@pytest.mark.anyio
async def test_a_gemini_failure_is_a_soft_stop(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        raise VideoUnavailableError("ClientError")

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result == VIDEO_UNAVAILABLE_MESSAGE
    assert run.sources == {}
    assert run.reserved == 0


@pytest.mark.anyio
async def test_an_unexpected_video_error_propagates(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        raise RuntimeError("bug")

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    with pytest.raises(RuntimeError):
        await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert run.reserved == 0


@pytest.mark.anyio
@pytest.mark.parametrize("notes", [VIDEO_NOT_DISCUSSED, "not discussed in this video"])
async def test_an_off_topic_video_records_nothing(
    notes: str,
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        return notes

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result == VIDEO_OFF_TOPIC_MESSAGE
    assert run.sources == {}


@pytest.mark.anyio
async def test_the_video_cap_is_a_soft_stop(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    tools = _tools(run)
    import agents.deep_forecaster.config as config
    from agents.deep_forecaster import state as state_module

    small = dataclasses.replace(config.LIMITS, max_videos=1)
    monkeypatch.setattr(tools_module, "LIMITS", small)
    monkeypatch.setattr(state_module, "LIMITS", small)
    first = "https://www.youtube.com/watch?v=abcdefghijk"
    second = "https://www.youtube.com/watch?v=defghijklmn"
    run.candidates[first] = _candidate(first, domain="youtube.com")
    run.candidates[second] = _candidate(second, domain="youtube.com")

    async def fake(video: str, question: str, store: Any = None) -> str:
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    await tools["ask"].ainvoke({"url": first, "question": "q"})
    result = await tools["ask"].ainvoke({"url": second, "question": "another q"})
    # Assert
    assert result == NO_VIDEOS_LEFT_MESSAGE
    assert run.videos == 1


@pytest.mark.anyio
async def test_every_progress_label_is_a_const(
    run: ResearchRun,
    events: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    tools = _tools(run)
    import re

    url = "https://www.youtube.com/watch?v=abcdefghijk"
    article = "https://carnegieendowment.org/x"

    async def fake_search(query: str, policy: Any) -> list[Candidate]:
        return [_candidate(article), _candidate(url, domain="youtube.com")]

    async def fake_fetch(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=article, text="text " * 100, author="A")]

    async def fake_watch(video: str, question: str, store: Any = None) -> str:
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "search_allowlisted", fake_search)
    monkeypatch.setattr(tools_module, "fetch_sources", fake_fetch)
    monkeypatch.setattr(tools_module, "watch_video", fake_watch)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "queries": ["q"]})
    await tools["read"].ainvoke({"urls": [article]})
    await tools["ask"].ainvoke({"url": url, "question": "q"})
    from agents.deep_forecaster.consts.progress import (
        READ_PROGRESS_LABEL,
        SEARCH_PROGRESS_LABEL,
        VIDEO_PROGRESS_LABEL,
    )

    templates = (SEARCH_PROGRESS_LABEL, READ_PROGRESS_LABEL, VIDEO_PROGRESS_LABEL)
    # Assert
    assert events, "progress frames must have been emitted"
    for event in events:
        assert isinstance(event, ProgressFrame)
        assert event.node == "deep_forecaster"
        match = re.fullmatch(
            "(?:"
            + "|".join(
                re.escape(template)
                .replace(r"\{used\}", r"\d+")
                .replace(r"\{cap\}", r"\d+")
                .replace(r"\{count\}", r"\d+")
                for template in templates
            )
            + ")",
            event.label,
        )
        assert match, event.label


@pytest.mark.anyio
async def test_ask_video_passes_the_run_store(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")
    received: list[Any] = []
    sentinel: Any = object()
    run.store = sentinel

    async def fake(video: str, question: str, store: Any = None) -> str:
        received.append(store)
        return "Notes."

    monkeypatch.setattr(tools_module, "watch_video", fake)
    await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert received == [sentinel]


@pytest.mark.anyio
async def test_ask_video_opens_a_watch_video_span(
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com", title="A talk")

    encountered: list[int] = []

    async def fake(video: str, question: str, store: Any = None) -> str:
        # The fake runs inside the wrapper: the current span must be the
        # `watch_video` span itself, or the Gemini spans it opens would be
        # orphans (review thread, #193).
        span = trace.get_current_span()
        span_id = span.get_span_context().span_id
        if span_id is None:
            pytest.fail("watch_video ran with no current span context")
        encountered.append(span_id)
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result.startswith("--- SOURCE ---")
    matches = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "watch_video"
    ]
    assert len(matches) == 1
    assert encountered == [matches[0].context.span_id]


@pytest.mark.anyio
async def test_a_search_batch_span_records_queries_results_and_budget(
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The `search_batch` span says what one batch did to the shared budget:
    whose sites, how many queries were asked and run, what came back, and
    what is left, so a Phoenix trace explains the run."""
    # Arrange
    found = [
        _candidate("https://carnegieendowment.org/a"),
        _candidate("https://carnegieendowment.org/b"),
    ]
    # Scripted in query order: one search with results, one empty, one failed.
    script: list[Any] = [found, [], SearchUnavailableError("Brave is down")]

    async def fake(query: str, policy: Any) -> list[Candidate]:
        outcome = script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        candidates: list[Candidate] = outcome
        return candidates

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["q1", "q2", "q3"]}
    )
    # Assert
    matches = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "search_batch"
    ]
    assert len(matches) == 1
    attributes = matches[0].attributes
    assert attributes is not None
    assert attributes["search.forecaster"] == "gabuev"
    assert attributes["search.queries_asked"] == 3
    assert attributes["search.queries_run"] == 3
    assert attributes["search.results"] == 2
    assert attributes["search.empty"] == 1
    assert attributes["search.failed"] == 1
    assert attributes["search.budget_left"] == LIMITS.max_searches - 3


@pytest.mark.anyio
async def test_a_read_batch_span_records_each_outcome(
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The `read_batch` span counts each outcome — read, already read,
    unreadable, refused — and the source room left, so a Phoenix trace
    explains a short batch."""
    # Arrange
    good = "https://carnegieendowment.org/good"
    already = "https://carnegieendowment.org/already"
    bad = "https://carnegieendowment.org/bad"
    unknown = "https://carnegieendowment.org/never-searched"
    for url in (good, already, bad):
        run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        # `bad` is the scripted unreadable page: the fetch finds no article text.
        if candidates[0].url == bad:
            return []
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    await tools["read"].ainvoke({"urls": [already]})
    captured_spans.clear()
    # Act
    await tools["read"].ainvoke({"urls": [good, already, bad, unknown]})
    # Assert
    matches = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "read_batch"
    ]
    assert len(matches) == 1
    attributes = matches[0].attributes
    assert attributes is not None
    assert attributes["read.urls_asked"] == 4
    assert attributes["read.pages_read"] == 1
    assert attributes["read.already_read"] == 1
    assert attributes["read.unreadable"] == 1
    assert attributes["read.refused"] == 1
    assert attributes["read.room_left"] == LIMITS.max_sources - 2


@pytest.mark.anyio
async def test_a_mixed_batch_renders_each_querys_own_block(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch's blocks are rendered per query, in query order: a hit lists
    `title | url` lines, an empty search the no-results message, a failed one
    the failure message — pairing a query with another's results or rendering
    a hit as a failure would go red (review thread)."""
    # Arrange: scripted in query order — one hit, one empty, one failed.
    script: list[Any] = [
        [_candidate("https://carnegieendowment.org/a", title="A title")],
        [],
        SearchUnavailableError("Brave is down"),
    ]

    async def fake(query: str, policy: Any) -> list[Candidate]:
        outcome = script.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        candidates: list[Candidate] = outcome
        return candidates

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": ["hit", "empty", "down"]}
    )
    # Assert
    assert result == (
        "Query: hit\nA title | https://carnegieendowment.org/a\n\n"
        f"Query: empty\n{NO_RESULTS_MESSAGE}\n\n"
        f"Query: down\n{SEARCH_FAILED_MESSAGE}\n\n"
        f"Searches left: {LIMITS.max_searches - 3}."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("text_chars", "cut"),
    [
        pytest.param(None, False, id="at the shown limit"),
        pytest.param(1, True, id="one past the shown limit"),
    ],
)
async def test_a_page_at_or_one_past_the_shown_limit(
    text_chars: int | None,
    cut: bool,
    tools: dict[str, BaseTool],
    run: ResearchRun,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cut boundary is exact: a page of exactly `max_shown_chars`
    characters shows whole, one past it carries the cut note (review thread)."""
    # Arrange
    url = "https://carnegieendowment.org/x"
    run.candidates[url] = _candidate(url)
    length = (
        LIMITS.max_shown_chars
        if text_chars is None
        else LIMITS.max_shown_chars + text_chars
    )

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return [Source(title="t", url=candidates[0].url, text="a" * length)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [url]})
    # Assert
    assert ("characters shown" in result) is cut


@pytest.mark.anyio
async def test_rereading_a_long_page_shows_it_cut_again(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-read shows the recorded page cut again, and the record keeps every
    character for the drafter and the writer (review thread)."""
    # Arrange
    url = "https://carnegieendowment.org/long"
    run.candidates[url] = _candidate(url)
    calls = 0

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        nonlocal calls
        calls += 1
        return [Source(title="t", url=url, text="a" * 20_000)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    first = await tools["read"].ainvoke({"urls": [url]})
    second = await tools["read"].ainvoke({"urls": [url]})
    # Assert
    assert calls == 1
    assert first == second
    assert "characters shown" in second
    assert len(run.sources[url].text) == 20_000


@pytest.mark.anyio
async def test_the_batch_cap_and_the_budget_cap_cut_together(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With two searches left, a seven-query batch runs two, and the remaining
    five are named by the two cut rules: `max_batch` cut the last two, the
    budget the two between (review thread)."""
    # Arrange
    tools = _tools(run)
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    import agents.deep_forecaster.config as config

    monkeypatch.setattr(
        tools_module, "LIMITS", dataclasses.replace(config.LIMITS, max_searches=2)
    )
    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {"forecaster": "gabuev", "queries": [f"q{n}" for n in range(1, 8)]}
    )
    # Assert
    assert len(calls) == 2
    assert run.searches == 2
    assert "Not run (no searches left): q3; q4; q5" in result
    assert "Not run (at most 5 queries per call): q6; q7" in result


@pytest.mark.anyio
async def test_queries_that_clean_to_the_same_text_spend_one_search(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dedup runs after cleaning: queries differing only by spacing or a
    `site:` operator are one query, so a model cannot spend two searches on
    results the scout already has (review thread)."""
    # Arrange
    calls: list[str] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append(query)
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke(
        {
            "forecaster": "gabuev",
            "queries": ["Russia China", " Russia  China ", "site:x.com Russia China"],
        }
    )
    # Assert
    assert calls == ["Gabuev Russia China"]
    assert run.searches == 1
    assert result.count("Query: ") == 1


@pytest.mark.anyio
async def test_a_recorded_page_is_reread_when_the_source_cap_is_full(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap check comes after the recorded-page lookup: with no room left,
    a page already read is still re-shown, and only a new URL is refused
    (review thread)."""
    # Arrange
    tools = _tools(run)
    import agents.deep_forecaster.config as config
    from agents.deep_forecaster import state as state_module

    small = dataclasses.replace(config.LIMITS, max_sources=1)
    monkeypatch.setattr(tools_module, "LIMITS", small)
    monkeypatch.setattr(state_module, "LIMITS", small)
    old = "https://carnegieendowment.org/old"
    new = "https://carnegieendowment.org/new"
    run.candidates[old] = _candidate(old)
    run.candidates[new] = _candidate(new)
    run.sources[old] = Source(title="t", url=old, text="old page text")

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise AssertionError("No room: nothing must be fetched")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"urls": [old, new]})
    # Assert
    assert "old page text" in result
    assert NO_SOURCES_LEFT_MESSAGE in result
    assert run.reserved == 0


@pytest.mark.anyio
async def test_a_failed_fetch_releases_its_reservation(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch that raises a bug releases the reservation it took, so one
    failing read cannot eat the source cap (review thread)."""
    # Arrange
    search, read, ask = build_tools(run)
    url = "https://carnegieendowment.org/x"
    run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise RuntimeError("the fetcher exploded")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act + Assert
    with pytest.raises(RuntimeError):
        await read.ainvoke({"urls": [url]})
    assert run.reserved == 0


@pytest.mark.anyio
async def test_parallel_batch_reads_run_at_most_the_fetch_gate_at_once(
    run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One gate bounds every scout's page fetches: `fetch_sources` bounds a
    call's own candidates only, so without the run-level gate three parallel
    five-URL batches would put 15 GETs on one site at once (review thread)."""
    # Arrange
    search, read, ask = build_tools(run)
    urls = [f"https://carnegieendowment.org/{n}" for n in range(15)]
    for url in urls:
        run.candidates[url] = _candidate(url)
    peak = 0
    current = 0

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.05)
        current -= 1
        return [Source(title="t", url=candidates[0].url, text="article text" * 50)]

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act: three parallel five-URL batches (a batch stops at `max_batch`),
    # fifteen distinct URLs in flight at once.
    await asyncio.gather(
        *[
            read.ainvoke({"urls": urls[i : i + LIMITS.max_batch]})
            for i in range(0, 15, LIMITS.max_batch)
        ]
    )
    # Assert: 15 parallel reads, each batch one URL at a time, under the gate.
    assert peak == 8
