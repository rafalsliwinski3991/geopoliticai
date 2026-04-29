import nodes.synthesize_perspectives as synthesize_perspectives
from models import Claim, Source, build_initial_pipeline_state


def _source(source_id: str) -> Source:
    return Source(
        id=source_id,
        title=f"Source {source_id}",
        url=f"https://example.com/{source_id}",
        notes="Source note.",
    )


def test_synthesize_perspectives_fallback_preserves_supported_claims(monkeypatch) -> None:
    state = build_initial_pipeline_state("What happened?", language="english")
    state["left_sources"] = [_source("L1")]
    state["centrist_sources"] = [_source("C1")]
    state["left_claims"] = [Claim(text="Shared factual claim.", source_ids=["L1"])]
    state["centrist_claims"] = [
        Claim(text="Shared factual claim.", source_ids=["C1"])
    ]
    state["right_claims"] = [Claim(text="Unsupported claim.", source_ids=[])]

    def _raise_invoke(**_kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(
        synthesize_perspectives, "invoke_structured_chain", _raise_invoke
    )

    result = synthesize_perspectives.synthesize_perspectives_agent(state)

    report = result["referee_report"]
    assert report.blocked is False
    assert result["right_claims"] == []
    assert len(result["synthesized_claims"]) == 1
    claim = result["synthesized_claims"][0]
    assert claim.text == "Shared factual claim."
    assert claim.asserted_by == ["left", "centrist"]
    assert claim.category == "consensus"
    assert claim.confidence == 0.70


def test_synthesize_perspectives_blocks_loaded_language() -> None:
    state = build_initial_pipeline_state("What happened?", language="english")
    state["left_sources"] = [_source("L1")]
    state["left_claims"] = [
        Claim(text="The policy treats opponents as traitors.", source_ids=["L1"])
    ]

    result = synthesize_perspectives.synthesize_perspectives_agent(state)

    report = result["referee_report"]
    assert report.blocked is True
    assert report.loaded_language == [
        "The policy treats opponents as traitors."
    ]
    assert result["synthesized_claims"] == []
