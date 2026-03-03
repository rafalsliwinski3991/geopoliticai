from __future__ import annotations

from geopoliticai.models import Claim
from geopoliticai.tools.referee import run_referee_checks


def _base_state() -> dict:
    return {
        "query": "Test query",
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "people_claims": [],
        "referee_report": {},
        "verification_to_do": [],
        "rewrites_to_do": [],
    }


def test_referee_filters_unsupported_claims_without_full_block() -> None:
    state = _base_state()
    state["left_claims"] = [Claim(text="According to L1, sourced claim.", source_ids=["L1"])]
    state["people_claims"] = [Claim(text="Unsourced claim text.", source_ids=[])]

    result = run_referee_checks(state)

    assert result["referee_report"]["blocked"] is False
    assert len(result["left_claims"]) == 1
    assert result["people_claims"] == []
    assert result["referee_report"]["unsupported_facts"] == ["Unsourced claim text."]
    assert result["verification_to_do"] == ["Unsourced claim text."]


def test_referee_blocks_when_all_claims_are_unsupported() -> None:
    state = _base_state()
    state["left_claims"] = [Claim(text="Unsupported A", source_ids=[])]
    state["right_claims"] = [Claim(text="Unsupported B", source_ids=[])]

    result = run_referee_checks(state)

    assert result["referee_report"]["blocked"] is True
    assert result["left_claims"] == []
    assert result["right_claims"] == []
