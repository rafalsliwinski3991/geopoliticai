import httpx
import pytest

from geopoliticai import search
from geopoliticai.models import Claim, ResearchPlan
from geopoliticai.nodes import generic_analyst


def _brave_response(results: list[dict]) -> httpx.Response:
    req = httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search")
    return httpx.Response(200, json={"web": {"results": results}}, request=req)


@pytest.fixture(autouse=True)
def _set_brave_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test-key")


def test_web_searcher_keeps_only_allowed_domains(monkeypatch) -> None:
    responses = [
        _brave_response(
            [
                {
                    "title": "Wikipedia entry",
                    "url": "https://en.wikipedia.org/wiki/Example",
                    "description": "Out-of-scope source that should be filtered.",
                },
                {
                    "title": "Brookings analysis",
                    "url": "https://www.brookings.edu/articles/example",
                    "description": "Allowed source should remain.",
                },
            ]
        )
    ]
    call_count = 0

    def fake_get(self, url, *, params, timeout):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    state = {
        "query": "test query",
        "research_plan": ResearchPlan(queries=["test query"]),
    }
    references = [("Brookings Institution", "https://www.brookings.edu")]

    sources = search.web_searcher(state, "centrist", references)  # type: ignore[arg-type]

    assert len(sources) == 1
    assert sources[0].url == "https://www.brookings.edu/articles/example"


def test_web_searcher_keeps_each_lane_within_configured_domains(monkeypatch) -> None:
    responses = [
        _brave_response(
            [
                {
                    "title": "CFR piece",
                    "url": "https://www.cfr.org/article/example",
                    "description": "Allowed base source.",
                },
                {
                    "title": "Wikipedia entry",
                    "url": "https://en.wikipedia.org/wiki/Example",
                    "description": "Must be dropped.",
                },
            ]
        ),
        _brave_response(
            [
                {
                    "title": "Economist note",
                    "url": "https://www.economist.com/world/2026/03/01/example",
                    "description": "Allowed extra source.",
                },
            ]
        ),
    ]
    call_count = 0

    def fake_get(self, url, *, params, timeout):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    state = {
        "query": "test query",
        "research_plan": ResearchPlan(queries=["test query"]),
    }
    references = [
        ("Council on Foreign Relations", "https://www.cfr.org"),
        ("The Economist", "https://www.economist.com"),
    ]

    sources = search.web_searcher(state, "centrist", references)  # type: ignore[arg-type]

    urls = [source.url for source in sources]
    assert "https://en.wikipedia.org/wiki/Example" not in urls
    assert "https://www.cfr.org/article/example" in urls
    assert "https://www.economist.com/world/2026/03/01/example" in urls


def test_build_biased_query_uses_reference_domain_without_path() -> None:
    query = search._build_biased_query(
        "query",
        [("Reuters Fact Check", "https://www.reuters.com/fact-check")],
    )
    assert "site:reuters.com" in query
    assert "site:reuters.com/fact-check" not in query


def test_analyst_claims_drop_unknown_source_ids() -> None:
    claims = [
        Claim(text="Allowed claim", source_ids=["C1"]),
        Claim(text="Mixed claim", source_ids=["C2", "WIKI1"]),
        Claim(text="Unknown claim", source_ids=["WIKI1"]),
    ]

    filtered = generic_analyst._keep_claims_with_allowed_sources(
        claims,
        {"C1", "C2"},
        log_label="centrist",
    )

    assert [claim.text for claim in filtered] == ["Allowed claim", "Mixed claim"]
    assert filtered[0].source_ids == ["C1"]
    assert filtered[1].source_ids == ["C2"]
