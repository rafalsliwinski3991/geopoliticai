import httpx
import pytest

import search
from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, SearchUnavailableError


def _response(results: list[dict[str, object]]) -> httpx.Response:
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
