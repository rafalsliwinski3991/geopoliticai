from __future__ import annotations

from unittest.mock import patch

from geopoliticai.agents.cross_check_facts import cross_check_facts_agent
from geopoliticai.models import Claim, Source


def _state_with_claims() -> dict:
    left_source = Source(
        id="L1",
        title="Left Seed",
        url="https://example.com/left/1",
        notes="Left source note.",
    )
    centrist_source = Source(
        id="C1",
        title="Centrist Seed",
        url="https://example.com/centrist/1",
        notes="Centrist source note.",
    )
    right_source = Source(
        id="R1",
        title="Right Seed",
        url="https://example.com/right/1",
        notes="Right source note.",
    )
    people_source = Source(
        id="P1",
        title="People Seed",
        url="https://example.com/people/1",
        notes="People source note.",
    )
    return {
        "query": "Test query",
        "left_claims": [Claim(text="Left claim", source_ids=["L1"])],
        "centrist_claims": [Claim(text="Centrist claim", source_ids=["C1"])],
        "right_claims": [Claim(text="Right claim", source_ids=["R1"])],
        "people_claims": [Claim(text="People claim", source_ids=["P1"])],
        "left_sources": [left_source],
        "centrist_sources": [centrist_source],
        "right_sources": [right_source],
        "people_sources": [people_source],
        "fact_sources": [],
    }


def _seed_fact_sources() -> dict:
    return {
        "fact": [
            Source(
                id="S1",
                title="Fact One",
                url="https://example.com/fact/1",
                notes="Fact note one",
            ),
            Source(
                id="S2",
                title="Fact Two",
                url="https://example.com/fact/2",
                notes="Fact note two",
            ),
        ]
    }


def test_cross_check_facts_falls_back_to_one_result_per_claim() -> None:
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    with patch(
        "geopoliticai.agents.cross_check_facts.invoke_structured_chain",
        return_value=_Obj(results=[]),
    ):
        result = cross_check_facts_agent(
            _state_with_claims(),
            infosphere_sources={"fact": [("Example", "https://example.com")]},
            language="english",
            seed_sources=_seed_fact_sources(),
        )

    fact_checks = result["fact_checks"]
    assert len(fact_checks) == 4
    assert all(item.verdict == "MISLEADING" for item in fact_checks)
    assert all(item.rationale for item in fact_checks)


def test_cross_check_facts_fuzzy_matches_claim_text_and_keeps_lane_source_ids() -> None:
    class _Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    state = _state_with_claims()
    state["left_claims"] = [
        Claim(
            text="According to L1, the coordinated joint attack by Israel and the United States on Iran began on 28 February 2026.",
            source_ids=["L1"],
        )
    ]
    state["centrist_claims"] = []
    state["right_claims"] = []
    state["people_claims"] = []

    llm_result = _Obj(
        results=[
            _Obj(
                claim_text="According to L1, the coordinated joint attack by Israel and US on Iran began on 28 February 2026",
                verdict="TRUE",
                rationale="Directly supported by the provided source.",
                source_ids=["L1"],
            )
        ]
    )

    with patch(
        "geopoliticai.agents.cross_check_facts.invoke_structured_chain",
        return_value=llm_result,
    ):
        result = cross_check_facts_agent(
            state,
            infosphere_sources={"fact": [("Example", "https://example.com")]},
            language="english",
            seed_sources=_seed_fact_sources(),
        )

    fact_checks = result["fact_checks"]
    assert len(fact_checks) == 1
    assert fact_checks[0].verdict == "TRUE"
    assert fact_checks[0].claim.text == state["left_claims"][0].text
    assert fact_checks[0].claim.source_ids == ["L1"]
