"""Governance nodes: referee, claim extraction, arbiter, and loop helpers."""

from __future__ import annotations

from geopoliticai.models import PipelineState, RefereeReport


LOADED_TERMS = ("traitor", "vermin", "subhuman")


def referee(state: PipelineState) -> PipelineState:
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


def extract_claims(state: PipelineState) -> PipelineState:
    extracted = []
    for lane, claims in (
        ("left", state["left_claims"]),
        ("centrist", state["centrist_claims"]),
        ("right", state["right_claims"]),
    ):
        for claim in claims:
            extracted.append(
                {
                    "text": claim.text,
                    "stmt_type": "INTERPRETATION",
                    "asserted_by": [lane],
                    "citations": claim.source_ids,
                    "confidence": 0.65,
                }
            )
    return {**state, "extracted_claims": extracted}


def arbiter_decide(state: PipelineState) -> PipelineState:
    if state["loop_count"] >= state["max_loops"] and (
        state["verification_to_do"] or state["rewrites_to_do"]
    ):
        return {
            **state,
            "decision": "ESCALATE",
            "decision_rationale": "Maximum verification loops reached.",
        }

    if state["verification_to_do"]:
        return {
            **state,
            "decision": "VERIFY",
            "decision_rationale": "Missing support for one or more claims.",
        }

    if state["rewrites_to_do"]:
        return {
            **state,
            "decision": "REVISE",
            "decision_rationale": "Loaded language detected in one or more claims.",
        }

    return {
        **state,
        "decision": "EXECUTE",
        "decision_rationale": "Referee checks passed.",
    }


def route_from_arbiter(state: PipelineState) -> str:
    return state.get("decision", "EXECUTE")


def verify_more(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending verifications for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "verification_to_do": [],
    }


def revise_analyses(state: PipelineState) -> PipelineState:
    # Minimal implementation: record loop and clear pending rewrites for next pass.
    return {
        **state,
        "loop_count": state["loop_count"] + 1,
        "rewrites_to_do": [],
    }
