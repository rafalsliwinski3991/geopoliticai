import httpx
import pytest

import search
from agents.expert.sources import EXPERT_SOURCES
from models import Candidate

_HTML = (
    "<html><body><article><p>"
    + ("Real reporting. " * 80)
    + "</p></article></body></html>"
)


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
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
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

    async def fake_extract(body: str) -> str:
        if "bad" in body:
            raise ValueError("broken parser")
        return "good " * 200

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_text", fake_extract)
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
    sources = await search.fetch_sources(candidates, EXPERT_SOURCES)
    assert len(sources) == 1 and sources[0].url.endswith("good")


@pytest.mark.anyio
async def test_all_extraction_failures_return_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    async def extract(body: str) -> str:
        raise ValueError("broken parser")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_text", extract)
    candidates = [Candidate("a", "https://reuters.com/a", "reuters.com")]
    assert await search.fetch_sources(candidates, EXPERT_SOURCES) == []


@pytest.mark.anyio
async def test_off_list_redirect_is_not_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    assert source is None
    assert requested == ["https://reuters.com/start"]


@pytest.mark.anyio
async def test_same_domain_redirect_is_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    async def extract(body: str) -> str:
        return "article " * 200

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(search, "_extract_text", extract)
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    assert source is not None
    assert requested == ["https://reuters.com/start", "https://reuters.com/final"]


@pytest.mark.anyio
async def test_redirect_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
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
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/start", "reuters.com"),
        EXPERT_SOURCES,
    )
    assert source is None
    assert len(requested) == search.MAX_REDIRECTS + 1


@pytest.mark.anyio
async def test_fetch_caps_extracted_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(
        self: httpx.AsyncClient,
        url: str,
        *,
        timeout: object | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return _html(_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async def extract(body: str) -> str:
        return "x " * 40_000

    monkeypatch.setattr(search, "_extract_text", extract)
    source = await search._fetch_and_extract(
        httpx.AsyncClient(),
        Candidate("t", "https://reuters.com/x", "reuters.com"),
        EXPERT_SOURCES,
    )
    assert source is not None and len(source.text) <= EXPERT_SOURCES.max_source_chars
