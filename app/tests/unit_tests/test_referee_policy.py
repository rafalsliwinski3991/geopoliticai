"""Lock the referee policy specified in docs/referee-policy.md.

If these tests fail, the implementation has drifted from the policy doc.
Update both at the same time, in the same PR.
"""

from __future__ import annotations

from geopoliticai.models import Claim, RefereeReport, build_initial_pipeline_state
from geopoliticai.nodes.referee import LOADED_TERMS, run_referee_checks


def _state_with_claims(**lanes: list[Claim]) -> dict:
    state = build_initial_pipeline_state("test", language="english")
    for lane, claims in lanes.items():
        state[f"{lane}_claims"] = claims
    return state


def test_loaded_terms_match_policy_doc() -> None:
    """docs/referee-policy.md is the source of truth for this list."""
    assert set(LOADED_TERMS) == {
        "traitor",
        "vermin",
        "subhuman",
        "enemy of the people",
        "scum",
        "filth",
        "cockroach",
        "parasite",
        "degenerate",
        "infestation",
    }


def test_blocks_when_any_loaded_term_present() -> None:
    state = _state_with_claims(
        left=[Claim(text="The opposition leader is a traitor.", source_ids=["L1"])],
    )
    result = run_referee_checks(state)
    report = result["referee_report"]
    assert isinstance(report, RefereeReport)
    assert report.blocked is True
    assert "The opposition leader is a traitor." in report.loaded_language


def test_blocks_when_all_claims_unsupported() -> None:
    state = _state_with_claims(
        left=[Claim(text="Unsupported assertion.", source_ids=[])],
        centrist=[Claim(text="Another unsupported claim.", source_ids=[])],
    )
    result = run_referee_checks(state)
    assert result["referee_report"].blocked is True


def test_passes_when_at_least_one_supported_and_no_loaded_terms() -> None:
    state = _state_with_claims(
        left=[Claim(text="A normal supported claim.", source_ids=["L1"])],
        centrist=[Claim(text="Another normal supported claim.", source_ids=["C1"])],
    )
    result = run_referee_checks(state)
    assert result["referee_report"].blocked is False


def test_strips_unsupported_claims_from_lane_lists() -> None:
    state = _state_with_claims(
        left=[
            Claim(text="Supported", source_ids=["L1"]),
            Claim(text="Unsupported", source_ids=[]),
        ],
    )
    result = run_referee_checks(state)
    # Lane list now contains only the supported claim.
    assert [c.text for c in result["left_claims"]] == ["Supported"]


def test_loaded_term_match_is_case_insensitive() -> None:
    state = _state_with_claims(
        right=[Claim(text="They are VERMIN, all of them.", source_ids=["R1"])],
    )
    result = run_referee_checks(state)
    assert result["referee_report"].blocked is True
