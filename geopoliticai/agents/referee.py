from __future__ import annotations

from geopoliticai.models import PipelineState, RefereeReport

LOADED_TERMS = ("traitor", "vermin", "subhuman")


def referee_agent(state: PipelineState) -> PipelineState:
    unsupported: list[str] = []
    loaded: list[str] = []
    all_claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    for claim in all_claims:
        if not claim.source_ids:
            unsupported.append(claim.text)
        low = claim.text.lower()
        if any(term in low for term in LOADED_TERMS):
            loaded.append(claim.text)

    report = RefereeReport(
        blocked=bool(unsupported or loaded),
        unsupported_facts=unsupported,
        loaded_language=loaded,
        required_verifications=unsupported,
        required_rewrites=loaded,
    )
    return {
        **state,
        "referee_report": {
            "blocked": report.blocked,
            "issues": report.issues,
            "unsupported_facts": report.unsupported_facts,
            "loaded_language": report.loaded_language,
            "required_verifications": report.required_verifications,
            "required_rewrites": report.required_rewrites,
        },
        "verification_to_do": report.required_verifications,
        "rewrites_to_do": report.required_rewrites,
    }
