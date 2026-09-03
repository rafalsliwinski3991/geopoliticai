import asyncio

import httpx
import pytest

import search
from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, SearchUnavailableError


def _response(results: list[object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"web": {"results": results}},
        request=httpx.Request("GET", search.BRAVE_SEARCH_URL),
    )


@pytest.fixture(autouse=True)
def _brave_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test-key")


def test_allowed_domain_accepts_subdomains_and_rejects_lookalikes() -> None:
    assert (
        search.allowed_domain("https://www.bbc.com/news", EXPERT_SOURCES) == "bbc.com"
    )
    assert (
        search.allowed_domain("https://edition.bbc.com/news", EXPERT_SOURCES)
        == "bbc.com"
    )
    assert (
        search.allowed_domain("https://bbc.com.evil.example/x", EXPERT_SOURCES) is None
    )


def test_batch_query_limits() -> None:
    built = search.build_batch_query("word " * 400, EXPERT_SOURCES.batches[0])
    assert len(built) <= search.BRAVE_MAX_QUERY_CHARS
    assert len(built.split()) <= search.BRAVE_MAX_QUERY_WORDS


def test_merge_caps_and_defers() -> None:
    batch = [
        Candidate("a", "https://reuters.com/1", "reuters.com"),
        Candidate("b", "https://reuters.com/2", "reuters.com"),
        Candidate("c", "https://reuters.com/3", "reuters.com"),
    ]
    merged = search.merge_candidates(
        [batch, [Candidate("d", "https://ft.com/1", "ft.com")]], EXPERT_SOURCES
    )
    assert [candidate.url for candidate in merged] == [
        "https://reuters.com/1",
        "https://reuters.com/2",
        "https://ft.com/1",
    ]


@pytest.mark.anyio
async def test_search_makes_exactly_three_batches_and_gates_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        value = params.get("q") if params else None
        if isinstance(value, str):
            calls.append(value)
        return _response(
            [
                {"title": "ok", "url": "https://reuters.com/article"},
                {"url": "https://evil.example/no"},
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    assert len(calls) == 3
    assert all(candidate.domain == "reuters.com" for candidate in candidates)


@pytest.mark.anyio
async def test_all_search_batches_failing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(SearchUnavailableError):
        await search.search_allowlisted("question", EXPERT_SOURCES)


@pytest.mark.anyio
async def test_malformed_brave_items_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One malformed Brave result must not abort a batch or reach the prompt."""

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        return _response(
            [
                {"title": "keep", "url": "https://reuters.com/article"},
                {"title": "bad url", "url": {"not": "a string"}},
                {"title": ["not", "a", "string"], "url": "https://apnews.com/1"},
                {"url": "https://ft.com/1"},
                "not-a-dict",
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    assert [candidate.url for candidate in candidates] == [
        "https://reuters.com/article",
        "https://apnews.com/1",
        "https://ft.com/1",
    ]
    # The array-typed title falls back to "Untitled" rather than crashing.
    assert candidates[1].title == "Untitled"


@pytest.mark.anyio
async def test_search_preserves_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled search batch must propagate, not be reported as a failure."""

    async def cancelled_batch(*args: object, **kwargs: object) -> list[Candidate]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(search, "_brave_batch", cancelled_batch)
    with pytest.raises(asyncio.CancelledError):
        await search.search_allowlisted("question", EXPERT_SOURCES)
