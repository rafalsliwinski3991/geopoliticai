"""Unit tests for `agents.deep_forecaster.tools`."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest
from langchain_core.tools import BaseTool
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import agents.deep_forecaster.tools as tools_module
from agents.deep_forecaster.consts.forecasters import FORECASTERS_BY_ID
from agents.deep_forecaster.prompts import VIDEO_NOT_DISCUSSED
from agents.deep_forecaster.state import ResearchRun
from agents.deep_forecaster.tools import (
    EMPTY_QUERY_MESSAGE,
    EMPTY_QUESTION_MESSAGE,
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
from models import Candidate, SearchUnavailableError, Source


def _candidate(url: str, domain: str | None = None, title: str = "t") -> Candidate:
    from urllib.parse import urlparse

    return Candidate(
        title,
        url,
        domain or urlparse(url).netloc.removeprefix("www.").removeprefix("m."),
    )


def _run(events: list[dict[str, Any]]) -> ResearchRun:
    return ResearchRun(writer=events.append)


def _tools(run: ResearchRun) -> dict[str, BaseTool]:
    search, read, ask = build_tools(run)
    return {"search": search, "read": read, "ask": ask}


@pytest.fixture
def events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def run(events: list[dict[str, Any]]) -> ResearchRun:
    return _run(events)


@pytest.fixture
def tools(run: ResearchRun) -> dict[str, BaseTool]:
    return _tools(run)


@pytest.mark.anyio
async def test_a_search_is_narrowed_to_one_forecaster(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    calls: list[tuple[str, Any]] = []

    async def fake(query: str, policy: Any) -> list[Candidate]:
        calls.append((query, policy))
        return []

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    await tools["search"].ainvoke({"forecaster": "gabuev", "query": "Russia China"})
    # Assert
    assert calls == [("Gabuev Russia China", calls[0][1])]
    assert calls[0][1].allowed_domains == ("carnegieendowment.org",)
    assert calls[0][1].batches == (("carnegieendowment.org",),)
    assert run.searches == 1


@pytest.mark.anyio
async def test_an_unknown_forecaster_spends_nothing(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    async def fake(query: str, policy: Any) -> list[Candidate]:
        raise AssertionError("Brave must not be called")

    monkeypatch.setattr(tools_module, "search_allowlisted", fake)
    # Act
    result = await tools["search"].ainvoke({"forecaster": "nobody", "query": "q"})
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
    result = await tools["search"].ainvoke({"forecaster": "gabuev", "query": "   "})
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
    await tools["search"].ainvoke({"forecaster": "gabuev", "query": "q"})
    result = await tools["search"].ainvoke({"forecaster": "gabuev", "query": "q again"})
    # Assert
    assert result == NO_SEARCHES_LEFT_MESSAGE
    assert len(calls) == 1


@pytest.mark.anyio
async def test_read_source_refuses_an_unknown_url(
    tools: dict[str, BaseTool], run: ResearchRun
) -> None:
    # Act
    result = await tools["read"].ainvoke({"url": "https://carnegieendowment.org/x"})
    # Assert
    assert result == UNKNOWN_URL_MESSAGE


@pytest.mark.anyio
async def test_read_source_refuses_a_video(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    run.candidates[url] = _candidate(url, domain="youtube.com")

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        raise AssertionError("A video must not be fetched")

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"url": url})
    # Assert
    assert result == VIDEO_URL_MESSAGE


@pytest.mark.anyio
async def test_read_source_shows_the_byline_and_the_asked_url(
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
    result = await tools["read"].ainvoke({"url": asked})
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
    result = await tools["read"].ainvoke({"url": url})
    # Assert
    assert result == NO_SOURCES_LEFT_MESSAGE
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
    results = await asyncio.gather(*[read.ainvoke({"url": url}) for _ in range(3)])
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
    results = await asyncio.gather(*[read.ainvoke({"url": url}) for url in urls])
    # Assert
    assert len(run.sources) == 2
    assert sum(1 for result in results if result == NO_SOURCES_LEFT_MESSAGE) == 3
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
    result = await tools["search"].ainvoke({"forecaster": "gabuev", "query": "q"})
    # Assert
    assert result == SEARCH_FAILED_MESSAGE
    assert run.searches == 1 and run.failed_searches == 1


@pytest.mark.anyio
async def test_searches_run_at_most_three_at_once(
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
        *[search.ainvoke({"forecaster": "gabuev", "query": f"q{n}"}) for n in range(6)]
    )
    # Assert
    assert peak == 3


@pytest.mark.anyio
async def test_read_source_unreadable_page_says_so_without_spending(
    tools: dict[str, BaseTool], run: ResearchRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    # Arrange
    url = "https://carnegieendowment.org/paywalled"
    run.candidates[url] = _candidate(url)

    async def fake(candidates: Any, policy: Any) -> list[Source]:
        return []

    monkeypatch.setattr(tools_module, "fetch_sources", fake)
    # Act
    result = await tools["read"].ainvoke({"url": url})
    # Assert
    assert result == UNREADABLE_MESSAGE
    assert run.sources == {}
    assert run.reserved == 0


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
    events: list[dict[str, Any]],
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
    await tools["search"].ainvoke({"forecaster": "gabuev", "query": "q"})
    await tools["read"].ainvoke({"url": article})
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
        assert event["node"] == "deep_forecaster"
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
            event["label"],
        )
        assert match, event["label"]


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

    async def fake(video: str, question: str, store: Any = None) -> str:
        return "Notes " * 40

    monkeypatch.setattr(tools_module, "watch_video", fake)
    # Act
    result = await tools["ask"].ainvoke({"url": url, "question": "q"})
    # Assert
    assert result.startswith("--- SOURCE ---") or "Gemini's notes" in result
    matches = [
        span
        for span in captured_spans.get_finished_spans()
        if span.name == "watch_video"
    ]
    assert len(matches) == 1
