"""Referee nodes for claim quality gates."""

from __future__ import annotations

from typing import Any

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


def run_referee_checks(state: PipelineState) -> dict[str, Any]:
    """Reject unsupported or loaded-language claims before synthesis."""
    unsupported: list[str] = []
    loaded: list[str] = []
    all_claims = (
        state["left_claims"]
        + state["centrist_claims"]
        + state["right_claims"]
        + state["people_claims"]
    )
    clean_left = [claim for claim in state["left_claims"] if claim.source_ids]
    clean_centrist = [claim for claim in state["centrist_claims"] if claim.source_ids]
    clean_right = [claim for claim in state["right_claims"] if claim.source_ids]
    clean_people = [claim for claim in state["people_claims"] if claim.source_ids]
    for claim in all_claims:
        if not claim.source_ids:
            unsupported.append(claim.text)
        low = claim.text.lower()
        if any(term in low for term in LOADED_TERMS):
            loaded.append(claim.text)

    total_claims = len(all_claims)
    has_some_supported = total_claims > len(unsupported)
    report = RefereeReport(
        blocked=bool(loaded) or not has_some_supported,
        unsupported_facts=unsupported,
        loaded_language=loaded,
    )
    return {
        "left_claims": clean_left,
        "centrist_claims": clean_centrist,
        "right_claims": clean_right,
        "people_claims": clean_people,
        "referee_report": report,
    }


def summarize_referee_block(state: PipelineState) -> dict[str, Any]:
    """Produce a synthesis when referee blocks normal downstream execution."""
    report = state.get("referee_report")
    if not isinstance(report, RefereeReport) or not report.blocked:
        return {}

    unsupported = report.unsupported_facts
    loaded = report.loaded_language
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
    return {"synthesis": synthesis}
