from __future__ import annotations

from geopoliticai.agents.generic_analyst import GenericClaimItem, _extract_claims


def test_extract_claims_repairs_missing_source_id_from_claim_text() -> None:
    claims = _extract_claims(
        [
            GenericClaimItem(
                text="According to P1, Donald Trump began his second term in 2025.",
                source_ids=[],
            )
        ]
    )

    assert len(claims) == 1
    assert claims[0].source_ids == ["P1"]


def test_extract_claims_keeps_provided_source_ids() -> None:
    claims = _extract_claims(
        [
            GenericClaimItem(
                text="According to L2, claim text.",
                source_ids=[" L2 ", "C1"],
            )
        ]
    )

    assert claims[0].source_ids == ["L2", "C1"]
