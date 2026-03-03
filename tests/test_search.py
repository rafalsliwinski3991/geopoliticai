from __future__ import annotations

from geopoliticai.models import Source
from geopoliticai.search import web_searcher


def _state() -> dict:
    return {"query": "test query", "research_plan": {"queries": []}}


def test_web_searcher_renumbers_seeded_sources_with_lane_prefix() -> None:
    seeded = [
        Source(
            id="S9",
            title="Left Source One",
            url="https://example.com/left/1",
            notes="note one",
        ),
        Source(
            id="S10",
            title="Left Source Two",
            url="https://example.com/left/2",
            notes="note two",
        ),
    ]

    sources = web_searcher(
        _state(),
        "left",
        [("Example", "https://example.com")],
        seed_sources=seeded,
    )

    assert [source.id for source in sources] == ["L1", "L2"]


def test_web_searcher_renumbers_dict_seeded_sources_for_fact_lane() -> None:
    seed_sources = {
        "fact": [
            Source(
                id="S1",
                title="Fact Source One",
                url="https://example.com/fact/1",
                notes="fact note one",
            ),
            Source(
                id="S2",
                title="Fact Source Two",
                url="https://example.com/fact/2",
                notes="fact note two",
            ),
        ]
    }

    sources = web_searcher(
        _state(),
        "fact",
        [("Example", "https://example.com")],
        seed_sources=seed_sources,
    )

    assert [source.id for source in sources] == ["F1", "F2"]
