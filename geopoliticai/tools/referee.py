from __future__ import annotations

from geopoliticai.models import PipelineState, RefereeReport

LOADED_TERMS = (
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
)


def run_referee_checks(state: PipelineState) -> PipelineState:
    unsupported: list[str] = []
    loaded: list[str] = []
    all_claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"] + state["people_claims"]
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


def summarize_referee_block(state: PipelineState) -> PipelineState:
    """Produce a synthesis when referee blocks normal downstream execution."""
    report = state.get("referee_report", {})
    if not report.get("blocked"):
        return state

    unsupported = report.get("unsupported_facts", [])
    loaded = report.get("loaded_language", [])
    language = state.get("language", "english")

    if language == "polish":
        lead = "Krotka odpowiedz: Brak wiarygodnej odpowiedzi przy obecnym stanie weryfikacji."
        details = [
            "Referee zablokowal publikacje wyniku i wymaga dodatkowej pracy.",
            f"- Tezy bez zrodel: {len(unsupported)}",
            f"- Tezy z jezykiem nacechowanym: {len(loaded)}",
        ]
    else:
        lead = "Short answer: A reliable answer cannot be provided with the current verification state."
        details = [
            "Referee blocked final publication and requested additional verification/rewrite work.",
            f"- Unsupported claims: {len(unsupported)}",
            f"- Loaded-language claims: {len(loaded)}",
        ]
    synthesis = "\n".join([lead, *details])
    return {**state, "synthesis": synthesis}
