import asyncio
from collections.abc import Mapping, Sequence

import httpx
import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agents.expert.consts.sources import EXPERT_SOURCES
from models import Candidate, SourcePolicy
from services import web_search
from shared.errors import SearchUnavailableError


def _response(results: list[object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"web": {"results": results}},
        request=httpx.Request("GET", web_search.BRAVE_SEARCH_URL),
    )


@pytest.fixture(autouse=True)
def _brave_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test-key")


def test_allowed_domain_accepts_subdomains_and_rejects_lookalikes() -> None:
    # Act + Assert
    assert (
        web_search.allowed_domain("https://www.bbc.com/news", EXPERT_SOURCES)
        == "bbc.com"
    )
    assert (
        web_search.allowed_domain("https://edition.bbc.com/news", EXPERT_SOURCES)
        == "bbc.com"
    )
    assert (
        web_search.allowed_domain("https://bbc.com.evil.example/x", EXPERT_SOURCES)
        is None
    )


def test_batch_query_limits() -> None:
    # Act
    built = web_search.build_batch_query("word " * 400, EXPERT_SOURCES.batches[0])
    # Assert
    assert len(built) <= web_search.BRAVE_MAX_QUERY_CHARS
    assert len(built.split()) <= web_search.BRAVE_MAX_QUERY_WORDS


def test_merge_caps_and_defers() -> None:
    # Arrange
    batch = [
        Candidate("a", "https://bbc.com/1", "bbc.com"),
        Candidate("b", "https://bbc.com/2", "bbc.com"),
        Candidate("c", "https://bbc.com/3", "bbc.com"),
    ]
    # Act
    merged = web_search.merge_candidates(
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
    candidates = await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
        await web_search.search_allowlisted("question", EXPERT_SOURCES)


@pytest.mark.anyio
async def test_brave_items_without_a_usable_url_or_title_are_handled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result with no url is skipped and one with no title reads "Untitled"."""

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
                {"title": "keep", "url": " https://bbc.com/article "},
                {"title": "no url"},
                {"url": "https://dw.com/1", "title": "  "},
                {"url": "https://bloomberg.com/1", "extra": "ignored"},
            ]
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act
    candidates = await web_search.search_allowlisted("question", EXPERT_SOURCES)
    # Assert
    assert {candidate.url: candidate.title for candidate in candidates} == {
        "https://bbc.com/article": "keep",
        "https://dw.com/1": "Untitled",
        "https://bloomberg.com/1": "Untitled",
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "body",
    [
        pytest.param([], id="the body is a list"),
        pytest.param({"web": "nope"}, id="web is not an object"),
        pytest.param({"web": {"results": {"a": 1}}}, id="results is not a list"),
        pytest.param(
            {"web": {"results": ["not-a-dict"]}}, id="a result is not an object"
        ),
        pytest.param(
            {"web": {"results": [{"url": {"not": "a string"}}]}},
            id="a url is not a string",
        ),
    ],
)
async def test_a_brave_body_of_the_wrong_shape_fails_the_batch(
    monkeypatch: pytest.MonkeyPatch, body: object
) -> None:
    # Arrange
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
        timeout: object | None = None,
    ) -> httpx.Response:
        return httpx.Response(
            200, json=body, request=httpx.Request("GET", web_search.BRAVE_SEARCH_URL)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    # Act + Assert
    with pytest.raises(SearchUnavailableError):
        await web_search.search_allowlisted("question", EXPERT_SOURCES)


@pytest.mark.anyio
async def test_search_preserves_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled search batch must propagate, not be reported as a failure."""

    # Arrange
    async def cancelled_batch(*args: object, **kwargs: object) -> list[Candidate]:
        raise asyncio.CancelledError()

    monkeypatch.setattr(web_search, "_brave_batch", cancelled_batch)
    # Act + Assert
    with pytest.raises(asyncio.CancelledError):
        await web_search.search_allowlisted("question", EXPERT_SOURCES)


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

    monkeypatch.setattr(web_search, "_brave_batch", fake_batch)
    # Act
    candidates = await web_search.search_allowlisted("question", EXPERT_SOURCES)
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

    monkeypatch.setattr(web_search, "_brave_batch", fake_batch)
    # Act
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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

    monkeypatch.setattr(web_search, "_brave_batch", failing_batch)
    # Act
    with pytest.raises(SearchUnavailableError):
        await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
    request = httpx.Request("GET", web_search.BRAVE_SEARCH_URL)
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

    monkeypatch.setattr(web_search, "_brave_batch", fake_batch)


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
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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

    monkeypatch.setattr(web_search, "_brave_batch", fake_batch)
    # Act
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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

    monkeypatch.setattr(web_search, "_brave_batch", failing_batch)
    # Act
    with pytest.raises(SearchUnavailableError):
        await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
    await web_search.search_allowlisted("question", EXPERT_SOURCES)
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
    label = web_search.describe_failure(error)
    # Assert
    assert label == expected


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
