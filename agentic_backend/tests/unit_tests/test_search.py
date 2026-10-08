import asyncio

import httpx
import pytest

import search
from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, SearchUnavailableError

_HTML = (
    "<html><body><article><p>"
    + ("Real reporting. " * 80)
    + "</p></article></body></html>"
)


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
    # Act + Assert
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
    # Act
    built = search.build_batch_query("word " * 400, EXPERT_SOURCES.batches[0])
    # Assert
    assert len(built) <= search.BRAVE_MAX_QUERY_CHARS
    assert len(built.split()) <= search.BRAVE_MAX_QUERY_WORDS


def test_merge_caps_and_defers() -> None:
    # Arrange
    batch = [
        Candidate("a", "https://reuters.com/1", "reuters.com"),
        Candidate("b", "https://reuters.com/2", "reuters.com"),
        Candidate("c", "https://reuters.com/3", "reuters.com"),
    ]
    # Act
    merged = search.merge_candidates(
        [batch, [Candidate("d", "https://ft.com/1", "ft.com")]], EXPERT_SOURCES
    )
    # Assert
    assert [candidate.url for candidate in merged] == [
        "https://reuters.com/1",
        "https://reuters.com/2",
        "https://ft.com/1",
    ]


@pytest.mark.anyio
async def test_search_makes_exactly_three_batches_and_gates_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
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
    # Act
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    # Assert
    assert len(calls) == 3
    assert all(candidate.domain == "reuters.com" for candidate in candidates)


@pytest.mark.anyio
async def test_all_search_batches_failing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await search.search_allowlisted("question", EXPERT_SOURCES)


@pytest.mark.anyio
async def test_malformed_brave_items_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One malformed Brave result must not abort a batch or reach the prompt."""

    # Arrange
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
    # Act
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    # Assert
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

    # Arrange
    async def cancelled_batch(*args: object, **kwargs: object) -> list[Candidate]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(search, "_brave_batch", cancelled_batch)
    # Act + Assert
    with pytest.raises(asyncio.CancelledError):
        await search.search_allowlisted("question", EXPERT_SOURCES)


def _html(
    body: str, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        headers=headers or {"content-type": "text/html"},
        request=httpx.Request("GET", "https://reuters.com/article"),
    )


@pytest.mark.anyio
async def test_fetch_failure_drops_source(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act + Assert
    assert (
        await search._fetch_and_extract(
            httpx.AsyncClient(),
            Candidate("t", "https://reuters.com/x", "reuters.com"),
            EXPERT_SOURCES,
        )
        is None
    )


@pytest.mark.anyio
async def test_mixed_extraction_failure_does_not_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    calls: list[str] = []

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        calls.append(url)
        return _html(_HTML)

    async def fake_extract_page(body: str) -> tuple[str | None, str]:
        if "bad" in body:
            raise ValueError("broken parser")
        return "good " * 200, ""

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_page", fake_extract_page)
    candidates = [
        Candidate("good", "https://reuters.com/good", "reuters.com"),
        Candidate("bad", "https://reuters.com/bad", "reuters.com"),
    ]

    # Make one body trigger the extraction exception.
    async def body_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html("bad" if url.endswith("bad") else _HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", body_get)
    # Act
    sources = await search.fetch_sources(candidates, EXPERT_SOURCES)
    # Assert
    assert len(sources) == 1 and sources[0].url.endswith("good")


@pytest.mark.anyio
async def test_all_extraction_failures_return_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    async def extract(body: str) -> tuple[str | None, str]:
        raise ValueError("broken parser")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_page", extract)
    candidates = [Candidate("a", "https://reuters.com/a", "reuters.com")]
    # Act + Assert
    assert await search.fetch_sources(candidates, EXPERT_SOURCES) == []


@pytest.mark.anyio
async def test_off_list_redirect_is_not_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    requested: list[str] = []

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        requested.append(url)
        return _html(
            "",
            302,
            {"location": "https://evil.example/payload", "content-type": "text/html"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is None
    assert requested == ["https://reuters.com/start"]


@pytest.mark.anyio
async def test_same_domain_redirect_is_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    requested: list[str] = []

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        requested.append(url)
        if url.endswith("start"):
            return _html("", 302, {"location": "/final", "content-type": "text/html"})
        return _html(_HTML)

    async def extract(body: str) -> tuple[str | None, str]:
        return "article " * 200, ""

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None
    assert requested == ["https://reuters.com/start", "https://reuters.com/final"]


@pytest.mark.anyio
async def test_redirect_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    requested: list[str] = []

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        requested.append(url)
        return _html(
            "",
            302,
            {
                "location": f"https://reuters.com/redirect-{len(requested)}",
                "content-type": "text/html",
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is None
    assert len(requested) == search.MAX_REDIRECTS + 1


@pytest.mark.anyio
async def test_fetch_caps_extracted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def extract(body: str) -> tuple[str | None, str]:
        return "x " * 40_000, ""

    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None and len(source.text) <= EXPERT_SOURCES.max_source_chars


@pytest.mark.anyio
async def test_a_fetched_page_carries_its_byline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    page = (
        "<html><head>"
        '<meta name="author" content="Alexander Gabuev">'
        "</head><body><article><p>"
        + ("Real reporting. " * 80)
        + "</p></article></body></html>"
    )

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            text=page,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://reuters.com/x"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None and source.author == "Alexander Gabuev"


@pytest.mark.anyio
async def test_a_page_without_a_byline_has_an_empty_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            text=_HTML,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://reuters.com/x"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None and source.author == ""


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        (
            '<html><head><script type="application/ld+json">'
            '{"@type": "NewsArticle", "author": {"@type": "Person", "name": "Brahma Chellaney"}}'
            "</script></head><body></body></html>",
            "Brahma Chellaney",
        ),
        (
            '<html><head><script type="application/ld+json">'
            '{"@graph": [{"@type": "Article", "author": [{"name": "A One"}, {"name": "B Two"}]}]}'
            "</script></head><body></body></html>",
            "A One, B Two",
        ),
        (
            '<html><head><script type="application/ld+json">'
            '{"@type": ["Article", "NewsArticle"], "author": "Jane Doe"}'
            "</script></head><body></body></html>",
            "Jane Doe",
        ),
        (
            '<html><head><script type="application/ld+json">'
            '{"@type": ["Person"], "author": "Jane Doe"}'
            "</script></head><body></body></html>",
            "Jane Doe",
        ),
        (
            "<html><head>"
            '<script type="application/ld+json">'
            '{"@type": "Article", "author": {"name": "Gabuev"}}'
            "</script>"
            '<meta name="author" content="Someone Else">'
            "</head><body></body></html>",
            "Gabuev",
        ),
        (
            '<html><head><meta name="author" content="Carnegie Endowment for International Peace">'
            "</head><body></body></html>",
            "Carnegie Endowment for International Peace",
        ),
        (
            '<html><head><script type="application/ld+json">'
            '{"@type": "Person", "name": "Charly Salonius-Pasternak"}'
            "</script></head><body></body></html>",
            "",
        ),
        (
            '<html><body><a rel="author" href="/people">John Bew</a>'
            "<article><p>" + ("Text. " * 100) + "</p></article></body></html>",
            "",
        ),
        (
            '<html><body><span class="byline">By Thomas Gomart</span>'
            "<article><p>" + ("Text. " * 100) + "</p></article></body></html>",
            "",
        ),
        (
            "<html><head>"
            '<script type="application/ld+json">{"@type": "Article", "author": </script>'
            '<script type="application/ld+json">'
            '{"@type": "Article", "author": {"name": "Chun"}}'
            "</script></head><body></body></html>",
            "Chun",
        ),
    ],
)
def test_byline_sync(page: str, expected: str) -> None:
    # Act + Assert
    assert search._byline_sync(page) == expected


def test_a_250_character_name_is_cut_to_200() -> None:
    # Arrange
    name = "N" * 250
    page = (
        f'<html><head><meta name="author" content="{name}"></head><body></body></html>'
    )
    # Act + Assert
    assert search._byline_sync(page) == name[:200]


@pytest.mark.anyio
async def test_a_byline_failure_keeps_the_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return httpx.Response(
            200,
            text=_HTML,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://reuters.com/x"),
        )

    def broken_feed(self: search._BylineParser, data: str) -> None:
        raise RuntimeError("broken jsonld")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search._BylineParser, "feed", broken_feed)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None and source.author == ""
