from __future__ import annotations

from unittest.mock import patch

from geopoliticai.agents.cross_check_facts import cross_check_facts_agent
from geopoliticai.models import Claim, Source


def _state_with_claims() -> dict:
    return {
        "query": "Test query",
        "left_claims": [Claim(text="Left claim", source_ids=["L1"])],
        "centrist_claims": [Claim(text="Centrist claim", source_ids=["C1"])],
        "right_claims": [Claim(text="Right claim", source_ids=["R1"])],
        "people_claims": [Claim(text="People claim", source_ids=["P1"])],
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
