import asyncio
import dataclasses
from collections.abc import Mapping

import httpx
import pytest
import trafilatura
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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

    async def fake_extract_page(body: str) -> search.ExtractedPage:
        if "bad" in body:
            raise ValueError("broken parser")
        return search.ExtractedPage("good " * 200, "", "", "")

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

    async def extract(body: str) -> search.ExtractedPage:
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

    async def extract(body: str) -> search.ExtractedPage:
        return search.ExtractedPage("article " * 200, "", "", "")

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

    async def extract(body: str) -> search.ExtractedPage:
        return search.ExtractedPage("x " * 40_000, "", "", "")

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


def _span_by_name(captured: InMemorySpanExporter, name: str) -> ReadableSpan:
    """The one finished span called `name`, with its attributes set."""
    matches = [
        span
        for span in captured.get_finished_spans()
        if span.name == name and span.attributes is not None
    ]
    assert len(matches) == 1, f"expected exactly one {name} span, got {len(matches)}"
    return matches[0]


def _attrs(span: ReadableSpan) -> Mapping[str, object]:
    """Return the span's attributes, typed `object` for plain asserts."""
    attributes: Mapping[str, object] = span.attributes or {}
    return attributes


@pytest.mark.anyio
async def test_fetch_span_records_cut_page(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    policy = dataclasses.replace(EXPERT_SOURCES, max_source_chars=20000)

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def extract(body: str) -> search.ExtractedPage:
        # A fake 40,000-character page body: one page, one outcome.
        return search.ExtractedPage("a" * 40_000, "", "", "")

    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        policy,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is not None
    attributes = _attrs(span)
    assert attributes["source.outcome"] == "ok"
    assert attributes["source.chars_full"] == 40000
    assert attributes["source.chars_kept"] == 20000
    assert attributes["source.truncated"] is True
    content_hash = attributes["source.content_hash"]
    assert isinstance(content_hash, str)
    assert len(content_hash) == 40
    assert set(content_hash) <= set("0123456789abcdef")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome",
    [
        "off_list",
        "fetch_failed",
        "redirect_limit",
        "not_html",
        "too_short",
        "extract_failed",
    ],
)
async def test_fetch_span_records_each_drop_reason(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    outcome: str,
) -> None:
    # Arrange
    async def slow_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    async def redirect_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(
            "",
            302,
            {"location": "https://reuters.com/loop", "content-type": "text/html"},
        )

    async def json_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _response([])

    async def html_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    if outcome == "off_list":
        fake_get = slow_response
        candidate = Candidate("t", "https://evil.example/x", "reuters.com")
    elif outcome == "fetch_failed":
        fake_get = slow_response
        candidate = Candidate("t", "https://reuters.com/x", "reuters.com")
    elif outcome == "redirect_limit":
        fake_get = redirect_response
        candidate = Candidate("t", "https://reuters.com/x", "reuters.com")
    elif outcome == "not_html":
        fake_get = json_response
        candidate = Candidate("t", "https://reuters.com/x", "reuters.com")
    else:
        fake_get = html_response
        candidate = Candidate("t", "https://reuters.com/x", "reuters.com")

    async def raising_extract(body: str) -> search.ExtractedPage:
        raise ValueError("broken parser")

    async def short_extract(body: str) -> search.ExtractedPage:
        return search.ExtractedPage("tiny", "", "", "")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    if outcome == "too_short":
        monkeypatch.setattr(search, "_extract_page", short_extract)
    else:
        monkeypatch.setattr(search, "_extract_page", raising_extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(), candidate, EXPERT_SOURCES
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is None
    assert _attrs(span)["source.outcome"] == outcome


@pytest.mark.anyio
async def test_extract_page_reads_date_and_declared_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("TZ", "UTC")
    body = (
        '<html lang="pl-PL"><head>'
        '<meta property="article:published_time" content="2025-03-01">'
        "</head><body><article><p>"
        + ("Real reporting. " * 80)
        + "</p></article></body></html>"
    )
    # Act
    page = await search._extract_page(body)
    # Assert
    assert page.lang == "pl"
    assert page.published == "2025-03-01"


@pytest.mark.anyio
async def test_extract_page_reads_declared_language_with_underscore_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    body = (
        '<html lang="pl_PL"><head>'
        '<meta property="article:published_time" content="2025-03-01">'
        "</head><body><article><p>"
        + ("Real reporting. " * 80)
        + "</p></article></body></html>"
    )
    # Act
    page = await search._extract_page(body)
    # Assert
    assert page.lang == "pl"


@pytest.mark.anyio
async def test_extract_page_ignores_dates_in_links() -> None:
    # Arrange
    body = (
        '<html><body><a href="/2023/01/10/other-story">x</a><article><p>'
        + ("Real reporting. " * 80)
        + "</p></article></body></html>"
    )
    # Act
    page = await search._extract_page(body)
    # Assert
    assert page.published == ""


@pytest.mark.anyio
async def test_a_telemetry_failure_keeps_the_page(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    def broken_attributes(*args: object, **kwargs: object) -> dict[str, object]:
        raise RuntimeError("broken attribute collector")

    monkeypatch.setattr(search, "_page_attributes", broken_attributes)

    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def extract(body: str) -> search.ExtractedPage:
        return search.ExtractedPage("article " * 200, "Byline", "", "")

    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is not None
    assert _attrs(span)["source.outcome"] == "ok"


@pytest.mark.anyio
async def test_extract_page_text_matches_trafilatura_extract() -> None:
    # Arrange
    body = (
        "<html><head><title>t</title></head><body><article>"
        "<h1>Heading</h1><p>First paragraph.</p><p>Second paragraph.</p>"
        "<ul><li>One</li><li>Two</li></ul>"
        "</article></body></html>"
    )
    # Act
    page = await search._extract_page(body)
    # Assert
    expected = trafilatura.extract(
        body, include_comments=False, include_tables=False, favor_precision=True
    )
    assert page.text == expected


@pytest.mark.anyio
async def test_an_overlong_html_lang_is_capped() -> None:
    # Arrange
    body = f'<html lang="a{search.MAX_LANG_CHARS}more"><body></body></html>'
    # Act
    page = await search._extract_page(body)
    # Assert
    assert len(page.lang) <= search.MAX_LANG_CHARS
