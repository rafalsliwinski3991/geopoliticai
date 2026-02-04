import pytest

pytest.importorskip("langgraph")

from geopoliticai.graph import run_pipeline
from geopoliticai.models import Source


@pytest.mark.parametrize(
    ("query", "left_claim", "centrist_claim", "right_claim", "synthesis"),
    [
        (
            "energy policy",
            "Left claim about energy",
            "Centrist claim about energy",
            "Right claim about energy",
            "Energy synthesis.",
        ),
        (
            "trade policy",
            "Left claim about trade",
            "Centrist claim about trade",
            "Right claim about trade",
            "Trade synthesis.",
        ),
    ],
)
def test_run_pipeline_with_seed_sources(
    monkeypatch,
    query,
    left_claim,
    centrist_claim,
    right_claim,
    synthesis,
):
    def fake_claims_llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
        if "perspective: leftist" in user:
            return {"claims": [{"text": left_claim, "source_ids": ["S1"]}]}
        if "perspective: centrist" in user:
            return {"claims": [{"text": centrist_claim, "source_ids": ["S2"]}]}
        return {"claims": [{"text": right_claim, "source_ids": ["S3"]}]}

    def fake_fact_llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
        return {
            "results": [
                {
                    "claim_text": left_claim,
                    "verdict": "TRUE",
                    "rationale": "Supported.",
                    "source_ids": ["S1"],
                }
            ]
        }

    def fake_summary_llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
        return {"synthesis": synthesis}

    monkeypatch.setattr("geopoliticai.claims.llm_json", fake_claims_llm_json)
    monkeypatch.setattr("geopoliticai.fact_check.llm_json", fake_fact_llm_json)
    monkeypatch.setattr("geopoliticai.summarizer.llm_json", fake_summary_llm_json)

    seed_sources = {
        "left": [Source(id="S1", title="Left Source", url="https://left.test", notes="n")],
        "centrist": [
            Source(id="S2", title="Centrist Source", url="https://centrist.test", notes="n")
        ],
        "right": [Source(id="S3", title="Right Source", url="https://right.test", notes="n")],
        "fact": [Source(id="S4", title="Fact Source", url="https://fact.test", notes="n")],
    }

    output = run_pipeline(query, seed_sources=seed_sources)

    assert left_claim in output
    assert centrist_claim in output
    assert right_claim in output
    assert synthesis in output
