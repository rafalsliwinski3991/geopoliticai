import search
from agents import generic_analyst
from models import Claim


class _FakeTavilyClient:
    def __init__(self, api_key: str, responses: list[dict]):
        self.api_key = api_key
        self._responses = responses
        self.calls = 0

    def search(self, _query: str, max_results: int, search_depth: str) -> dict:
        assert max_results >= 1
        assert search_depth == "advanced"
        response = self._responses[self.calls]
        self.calls += 1
        return response


def test_web_searcher_keeps_only_allowed_domains(monkeypatch) -> None:
    responses = [
        {
            "results": [
                {
                    "title": "Wikipedia entry",
                    "url": "https://en.wikipedia.org/wiki/Example",
                    "content": "Out-of-scope source that should be filtered.",
                },
                {
                    "title": "Brookings analysis",
                    "url": "https://www.brookings.edu/articles/example",
                    "content": "Allowed source should remain.",
                },
            ]
        }
    ]
    fake_client = _FakeTavilyClient("test", responses)
    monkeypatch.setenv("TAVILY_KEY", "test-key")
    monkeypatch.setattr(search, "TavilyClient", lambda api_key: fake_client)

    state = {"query": "test query", "research_plan": {"queries": ["test query"]}}
    references = [("Brookings Institution", "https://www.brookings.edu")]

    sources = search.web_searcher(
        state,  # type: ignore[arg-type]
        "centrist",
        references,
    )

    assert len(sources) == 1
    assert sources[0].url == "https://www.brookings.edu/articles/example"


def test_web_searcher_keeps_each_lane_within_configured_domains(monkeypatch) -> None:
    responses = [
        {
            "results": [
                {
                    "title": "CFR piece",
                    "url": "https://www.cfr.org/article/example",
                    "content": "Allowed base source.",
                },
                {
                    "title": "Wikipedia entry",
                    "url": "https://en.wikipedia.org/wiki/Example",
                    "content": "Must be dropped.",
                }
            ]
        },
        {
            "results": [
                {
                    "title": "Economist note",
                    "url": "https://www.economist.com/world/2026/03/01/example",
                    "content": "Allowed extra source.",
                },
            ]
        },
    ]
    fake_client = _FakeTavilyClient("test", responses)
    monkeypatch.setenv("TAVILY_KEY", "test-key")
    monkeypatch.setattr(search, "TavilyClient", lambda api_key: fake_client)

    state = {"query": "test query", "research_plan": {"queries": ["test query"]}}
    references = [
        ("Council on Foreign Relations", "https://www.cfr.org"),
        ("The Economist", "https://www.economist.com"),
    ]

    sources = search.web_searcher(
        state,  # type: ignore[arg-type]
        "centrist",
        references,
    )

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
