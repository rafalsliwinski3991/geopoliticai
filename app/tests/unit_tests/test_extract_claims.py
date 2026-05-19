"""Verify the Send-based fan-out wiring for claim extraction."""

from __future__ import annotations

from langgraph.types import Send

from geopoliticai.models import Claim, build_initial_pipeline_state
from geopoliticai.nodes.extract_claims import (
    extract_claims_for_verification,
    extract_claims_lane,
    fan_out_extract,
)


def _state_with_claims() -> dict:
    state = build_initial_pipeline_state("q", language="english")
    state["left_claims"] = [Claim(text="L", source_ids=["L1"])]
    state["centrist_claims"] = [Claim(text="C", source_ids=["C1"])]
    state["right_claims"] = [Claim(text="R", source_ids=["R1"])]
    state["people_claims"] = [Claim(text="P", source_ids=["P1"])]
    return state


def test_fan_out_dispatches_one_send_per_lane() -> None:
    sends = fan_out_extract(_state_with_claims())  # type: ignore[arg-type]
    assert len(sends) == 4
    assert all(isinstance(s, Send) for s in sends)
    assert [s.node for s in sends] == [
        "extract_claims_lane",
        "extract_claims_lane",
        "extract_claims_lane",
        "extract_claims_lane",
    ]
    assert {s.arg["lane"] for s in sends} == {"left", "centrist", "right", "people"}


def test_extract_claims_lane_emits_records_for_its_lane() -> None:
    result = extract_claims_lane(
        {"lane": "left", "claims": [Claim(text="hello", source_ids=["L1"])]}
    )
    assert result == {
        "extracted_claims": [
            {
                "text": "hello",
                "stmt_type": "INTERPRETATION",
                "asserted_by": ["left"],
                "citations": ["L1"],
                "confidence": 0.65,
            }
        ]
    }


def test_legacy_sequential_extractor_matches_aggregated_lane_workers() -> None:
    """The sequential path produces the same records the Send fan-out would
    yield once the reducer merges all four workers' outputs."""
    state = _state_with_claims()
    sequential = extract_claims_for_verification(state)["extracted_claims"]  # type: ignore[arg-type]

    parallel: list[dict] = []
    for send in fan_out_extract(state):  # type: ignore[arg-type]
        parallel.extend(extract_claims_lane(send.arg)["extracted_claims"])

    assert sequential == parallel
