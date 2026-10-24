import asyncio
import dataclasses
import unicodedata
from collections.abc import Mapping, Sequence

import httpx
import pytest
import trafilatura
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import search
from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, SearchUnavailableError, SourcePolicy

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
        Candidate("a", "https://bbc.com/1", "bbc.com"),
        Candidate("b", "https://bbc.com/2", "bbc.com"),
        Candidate("c", "https://bbc.com/3", "bbc.com"),
    ]
    # Act
    merged = search.merge_candidates(
        [batch, [Candidate("d", "https://bloomberg.com/1", "bloomberg.com")]],
        EXPERT_SOURCES,
    )
    # Assert
    assert [candidate.url for candidate in merged] == [
        "https://bbc.com/1",
        "https://bbc.com/2",
        "https://bloomberg.com/1",
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
                {"title": "ok", "url": "https://bbc.com/article"},
                {"url": "https://evil.example/no"},
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    # Assert
    assert len(calls) == 3
    assert all(candidate.domain == "bbc.com" for candidate in candidates)


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
                {"title": "keep", "url": "https://bbc.com/article"},
                {"title": "bad url", "url": {"not": "a string"}},
                {"title": ["not", "a", "string"], "url": "https://dw.com/1"},
                {"url": "https://bloomberg.com/1"},
                "not-a-dict",
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    # Assert
    assert [candidate.url for candidate in candidates] == [
        "https://bbc.com/article",
        "https://dw.com/1",
        "https://bloomberg.com/1",
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


@pytest.mark.anyio
async def test_search_span_counts_results_and_failed_batches(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """One failed batch must not lose the surviving batches' counts on the span."""

    # Arrange
    async def fake_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        if "bbc.com" in domains:
            return [
                Candidate("r1", "https://bbc.com/one", "bbc.com"),
                Candidate("r2", "https://bbc.com/two", "bbc.com"),
            ]
        if "dw.com" in domains:
            return [Candidate("a1", "https://dw.com/one", "dw.com")]
        raise httpx.ConnectError("batch down")

    monkeypatch.setattr(search, "_brave_batch", fake_batch)
    # Act
    candidates = await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert len(candidates) == 3  # 2 bbc + 1 dw survive the merge
    attributes = _attrs(span)
    assert attributes["search.batches"] == 3
    assert attributes["search.failed_batches"] == 1
    per_batch = attributes["search.results_per_batch"]
    # OTel records sequence attributes as tuples; normalize before comparing.
    assert isinstance(per_batch, tuple)
    assert list(per_batch) == [2, 1]
    assert attributes["search.candidates"] == len(candidates)


@pytest.mark.anyio
async def test_search_span_names_the_policy_domains(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    async def fake_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        return [Candidate("a", "https://bbc.com/one", "bbc.com")]

    monkeypatch.setattr(search, "_brave_batch", fake_batch)
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    # OTel records sequence attributes as tuples; normalize before comparing.
    recorded = _attrs(span)["search.domains"]
    assert isinstance(recorded, tuple)
    assert list(recorded) == sorted(EXPERT_SOURCES.allowed_domains)


@pytest.mark.anyio
async def test_the_search_span_records_every_batch_failing(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    # Arrange
    async def failing_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        raise httpx.ConnectError("batch down")

    monkeypatch.setattr(search, "_brave_batch", failing_batch)
    # Act
    with pytest.raises(SearchUnavailableError):
        await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    attributes = _attrs(span)
    assert attributes["search.batches"] == len(EXPERT_SOURCES.batches)
    assert attributes["search.failed_batches"] == attributes["search.batches"]
    per_batch = attributes["search.results_per_batch"]
    assert isinstance(per_batch, tuple)
    assert list(per_batch) == []
    assert "search.candidates" not in attributes


def _status_error(status: int) -> httpx.HTTPStatusError:
    """The error `raise_for_status` raises for a response with this status."""
    request = httpx.Request("GET", search.BRAVE_SEARCH_URL)
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("refused", request=request, response=response)


def _fail_one_batch_with(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    """Make the first Brave batch raise `error` and the others return a result."""

    async def fake_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        if "bbc.com" in domains:
            raise error
        return [Candidate("a1", "https://dw.com/one", "dw.com")]

    monkeypatch.setattr(search, "_brave_batch", fake_batch)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, "429"), (402, "402"), (500, "500")],
    ids=["rate limit 429", "quota 402", "server 500"],
)
async def test_a_failed_brave_batch_records_its_http_status_on_the_span(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    status: int,
    expected: str,
) -> None:
    """A rate limit, an exhausted quota, and an outage need different fixes, so the trace names the status."""
    # Arrange
    _fail_one_batch_with(monkeypatch, _status_error(status))
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == (expected,)


@pytest.mark.anyio
async def test_a_timed_out_brave_batch_records_timeout(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A slow Brave is not a refusing Brave; the trace must tell them apart."""
    # Arrange
    _fail_one_batch_with(monkeypatch, httpx.ReadTimeout("slow"))
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == ("timeout",)


@pytest.mark.anyio
async def test_any_other_brave_failure_records_its_exception_class(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A dropped connection has no status, so the trace falls back to the error's class."""
    # Arrange
    _fail_one_batch_with(monkeypatch, httpx.ConnectError("boom"))
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == ("ConnectError",)


@pytest.mark.anyio
async def test_a_search_with_no_failed_batch_records_no_failures(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """An empty list tells a reader the batches were checked and all answered."""

    # Arrange
    async def fake_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        return [Candidate("a", "https://bbc.com/one", "bbc.com")]

    monkeypatch.setattr(search, "_brave_batch", fake_batch)
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == ()


@pytest.mark.anyio
async def test_every_batch_failing_still_records_the_causes(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The run that dies of Brave is the one whose causes matter most."""

    # Arrange
    async def failing_batch(
        client: httpx.AsyncClient,
        query: str,
        domains: Sequence[str],
        policy: SourcePolicy,
    ) -> list[Candidate]:
        raise _status_error(429)

    monkeypatch.setattr(search, "_brave_batch", failing_batch)
    # Act
    with pytest.raises(SearchUnavailableError):
        await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == ("429",) * len(EXPERT_SOURCES.batches)


@pytest.mark.anyio
async def test_the_recorded_failure_never_carries_the_error_message(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """An error's text can hold a URL or a header, and a span is exported."""
    # Arrange
    secret = "X-Subscription-Token: secret-token-123"
    _fail_one_batch_with(monkeypatch, RuntimeError(secret))
    # Act
    await search.search_allowlisted("question", EXPERT_SOURCES)
    span = _span_by_name(captured_spans, "brave_search")
    # Assert
    assert _attrs(span)["search.failures"] == ("RuntimeError",)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(403), "403"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.ConnectError("boom"), "ConnectError"),
        (ValueError("bad"), "ValueError"),
    ],
    ids=["http status", "timeout", "transport error", "non-http error"],
)
def test_describe_failure_names_status_timeout_or_class(
    error: BaseException, expected: str
) -> None:
    """One short label per cause keeps spans comparable and free of error text."""
    # Act
    label = search.describe_failure(error)
    # Assert
    assert label == expected


def _html(
    body: str, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        headers=headers or {"content-type": "text/html"},
        request=httpx.Request("GET", "https://bbc.com/article"),
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
            Candidate("t", "https://bbc.com/x", "bbc.com"),
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
        Candidate("good", "https://bbc.com/good", "bbc.com"),
        Candidate("bad", "https://bbc.com/bad", "bbc.com"),
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
    candidates = [Candidate("a", "https://bbc.com/a", "bbc.com")]
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
        Candidate("t", "https://bbc.com/start", "bbc.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is None
    assert requested == ["https://bbc.com/start"]


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
        Candidate("t", "https://bbc.com/start", "bbc.com"),
        EXPERT_SOURCES,
    )
    # Assert
    assert source is not None
    assert requested == ["https://bbc.com/start", "https://bbc.com/final"]


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
                "location": f"https://bbc.com/redirect-{len(requested)}",
                "content-type": "text/html",
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/start", "bbc.com"),
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
        Candidate("t", "https://bbc.com/x", "bbc.com"),
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
            request=httpx.Request("GET", "https://bbc.com/x"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
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
            request=httpx.Request("GET", "https://bbc.com/x"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
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
            request=httpx.Request("GET", "https://bbc.com/x"),
        )

    def broken_feed(self: search._BylineParser, data: str) -> None:
        raise RuntimeError("broken jsonld")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search._BylineParser, "feed", broken_feed)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
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
        return search.ExtractedPage("a" * 40_000, "A. Byline", "2025-03-01", "pl")

    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
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
    assert attributes["source.domain"] == "bbc.com"
    assert attributes["source.url"] == "https://bbc.com/x"
    assert attributes["source.lang"] == "pl"
    assert attributes["source.published"] == "2025-03-01"
    content_hash = attributes["source.content_hash"]
    assert isinstance(content_hash, str)
    assert len(content_hash) == 40
    assert set(content_hash) <= set("0123456789abcdef")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("text_len", "expected_truncated"),
    [(599, False), (600, False), (601, True)],
)
async def test_fetch_span_keeps_text_at_the_cap_edges(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    text_len: int,
    expected_truncated: bool,
) -> None:
    # Arrange
    # A 600-character cap just above the policy's 500-character `too_short`
    # floor: the cap-1, cap, and cap+1 edges.
    policy = dataclasses.replace(EXPERT_SOURCES, max_source_chars=600)

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
        return search.ExtractedPage("a" * text_len, "", "", "")

    monkeypatch.setattr(search, "_extract_page", extract)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
        policy,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is not None
    attributes = _attrs(span)
    assert attributes["source.chars_full"] == text_len
    assert attributes["source.chars_kept"] == min(text_len, 600)
    assert attributes["source.truncated"] is expected_truncated


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("label", "expected_outcome"),
    [
        ("off_list", "off_list"),
        ("fetch_failed", "fetch_failed"),
        ("redirect_limit", "redirect_limit"),
        ("not_html", "not_html"),
        ("too_short", "too_short"),
        ("extract_failed", "extract_failed"),
        # One trigger per branch label: a status error is a distinct trigger
        # for the `fetch_failed` outcome, an off-list redirect is a distinct
        # trigger for `off_list`, and a missing Location is a distinct trigger
        # for `redirect_limit` (review thread, #192).
        ("404_is_a_fetch_failure", "fetch_failed"),
        ("off_list_redirect", "off_list"),
        ("redirect_with_no_location", "redirect_limit"),
    ],
)
async def test_fetch_span_records_each_drop_reason(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    label: str,
    expected_outcome: str,
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
            {"location": "https://bbc.com/loop", "content-type": "text/html"},
        )

    async def off_list_redirect_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(
            "",
            302,
            {"location": "https://evil.example/x", "content-type": "text/html"},
        )

    async def redirect_without_a_location_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html("", 302, {"content-type": "text/html"})

    async def error_status_response(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html("", 404)

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

    candidate = Candidate("t", "https://bbc.com/x", "bbc.com")
    if label == "off_list":
        fake_get = slow_response
        candidate = Candidate("t", "https://evil.example/x", "bbc.com")
    elif label == "fetch_failed":
        fake_get = slow_response
    elif label == "404_is_a_fetch_failure":
        fake_get = error_status_response
    elif label == "redirect_limit":
        fake_get = redirect_response
    elif label == "redirect_with_no_location":
        fake_get = redirect_without_a_location_response
    elif label == "off_list_redirect":
        fake_get = off_list_redirect_response
    elif label == "not_html":
        fake_get = json_response
    else:
        fake_get = html_response

    async def raising_extract(body: str) -> search.ExtractedPage:
        raise ValueError("broken parser")

    async def short_extract(body: str) -> search.ExtractedPage:
        return search.ExtractedPage("tiny", "", "", "")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    if label == "too_short":
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
    assert _attrs(span)["source.outcome"] == expected_outcome


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (403, None, "403"),
        (404, None, "404"),
        (None, httpx.ReadTimeout("slow"), "timeout"),
    ],
    ids=["http 403", "http 404", "timeout"],
)
async def test_a_failed_fetch_records_its_cause_on_the_span(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
    status: int | None,
    error: httpx.HTTPError | None,
    expected: str,
) -> None:
    """A blocked page and a slow page both read `fetch_failed`; the cause says which site to give up on."""

    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        if error is not None:
            raise error
        return _html("", status or 0)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
        EXPERT_SOURCES,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is None
    attributes = _attrs(span)
    assert attributes["source.outcome"] == "fetch_failed"
    assert attributes["source.failure"] == expected


@pytest.mark.anyio
async def test_a_page_that_loads_records_no_failure(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A kept page has no failure; an empty value would read as a cause."""

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
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
        EXPERT_SOURCES,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is not None
    assert "source.failure" not in _attrs(span)


@pytest.mark.anyio
async def test_an_off_list_redirect_records_no_failure(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """An off-list redirect is our own gate working, not a site failing."""

    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(
            "",
            302,
            {"location": "https://evil.example/x", "content-type": "text/html"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://bbc.com/x", "bbc.com"),
        EXPERT_SOURCES,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is None
    attributes = _attrs(span)
    assert attributes["source.outcome"] == "off_list"
    assert "source.failure" not in attributes


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
        Candidate("t", "https://bbc.com/x", "bbc.com"),
        EXPERT_SOURCES,
    )
    span = _span_by_name(captured_spans, "fetch_source")
    # Assert
    assert source is not None
    assert _attrs(span)["source.outcome"] == "ok"


@pytest.mark.anyio
async def test_extract_page_text_matches_trafilatura_extract() -> None:
    # Arrange
    overwritten = "Údolí"
    decomposed = unicodedata.normalize("NFD", overwritten)
    body = (
        "<html><head><title>t</title></head><body><article>"
        f"<h1>{decomposed}Údolí</h1><p>First paragraph.</p><p>Second paragraph.</p>"
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
    assert page.text is not None and overwritten in page.text
    # The match is not settled by the page itself being NFC: a decomposed body
    # must come back normalized to the same text as `extract` would return.
    assert page.text == unicodedata.normalize("NFC", page.text)


@pytest.mark.anyio
async def test_an_overlong_html_lang_is_capped() -> None:
    # Arrange
    lang_value = "a" * 100
    body = f'<html lang="{lang_value}"><body></body></html>'
    # Act
    page = await search._extract_page(body)
    # Assert
    assert page.lang == search.MAX_LANG_CHARS * "a"
