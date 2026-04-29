"""Fact-checking agent for verifying claims against sources."""

import logging
from difflib import SequenceMatcher
from typing import Any, List, Literal

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from config import get_model
from llm import invoke_structured_chain
from models import Claim, FactCheckResult, PipelineState, Source, SynthesizedClaim
from nodes.runtime_config import runtime_infosphere_sources, runtime_language
from search import web_searcher

logger = logging.getLogger(__name__)
SUPPORTED_VERDICTS = {"TRUE", "PARTIALLY_TRUE", "CONTESTED", "UNVERIFIED"}
CLAIM_MATCH_THRESHOLD = 0.85


class FactCheckItem(BaseModel):
    """Single fact-check result for a claim."""

    claim_text: str = ""
    verdict: (
        Literal["TRUE", "PARTIALLY_TRUE", "CONTESTED", "UNVERIFIED"] | str
    ) = ""
    confidence: float = 0.0
    rationale: str = ""
    source_ids: List[str] = Field(default_factory=list)
    supporting_source_ids: List[str] = Field(default_factory=list)
    contradicting_source_ids: List[str] = Field(default_factory=list)

    @field_validator(
        "source_ids",
        "supporting_source_ids",
        "contradicting_source_ids",
        mode="before",
    )
    @classmethod
    def _coerce_source_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]


class FactCheckOutput(BaseModel):
    """Structured output for a batch of fact-check results."""

    results: List[FactCheckItem] = Field(default_factory=list)


def _normalize_text(text: str) -> str:
    """Normalize claim text for approximate matching."""
    return " ".join((text or "").lower().split())


def _find_best_claim_match(
    candidate_text: str,
    claims_by_text: dict[str, Claim],
    threshold: float = CLAIM_MATCH_THRESHOLD,
) -> str | None:
    """Map a near-duplicate claim text back to the original input claim text."""
    normalized_candidate = _normalize_text(candidate_text)
    if not normalized_candidate:
        return None

    best_ratio = 0.0
    best_match: str | None = None
    for original_text in claims_by_text:
        ratio = SequenceMatcher(
            None,
            normalized_candidate,
            _normalize_text(original_text),
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = original_text

    if best_ratio >= threshold:
        return best_match
    return None


def _dedupe_sources_by_url(sources: list[Source]) -> list[Source]:
    """Deduplicate context sources by URL while preserving first occurrence."""
    deduped: list[Source] = []
    seen_keys: set[str] = set()
    for source in sources:
        dedupe_key = source.url.strip() or f"__id__:{source.id}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(source)
    return deduped


def _normalize_verdict(value: str) -> str:
    """Return canonical weighted verdict labels."""
    verdict = " ".join((value or "").strip().upper().replace("-", "_").split())
    verdict = verdict.replace(" ", "_")
    if verdict in {"PARTIALLYTRUE", "PARTLY_TRUE", "PARTIAL_TRUE"}:
        verdict = "PARTIALLY_TRUE"
    if verdict in {"MISLEADING", "FALSE"}:
        verdict = "UNVERIFIED"
    if verdict not in SUPPORTED_VERDICTS:
        return "UNVERIFIED"
    return verdict


def _confidence_for_verdict(verdict: str, model_confidence: float) -> float:
    """Clamp model confidence into the tier implied by the verdict."""
    try:
        confidence = float(model_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    if confidence:
        return confidence
    if verdict == "TRUE":
        return 0.85
    if verdict == "PARTIALLY_TRUE":
        return 0.65
    if verdict == "CONTESTED":
        return 0.40
    return 0.20


def _fallback_result_for_claim(claim: Claim, rationale: str) -> FactCheckResult:
    """Build a deterministic fallback fact-check result for one claim."""
    return FactCheckResult(
        claim=Claim(text=claim.text, source_ids=[]),
        verdict="UNVERIFIED",
        confidence=0.20,
        rationale=rationale,
    )


def _synthesized_claims_for_fact_check(state: PipelineState) -> list[SynthesizedClaim]:
    """Return synthesized claims or a backward-compatible lane-claim fallback."""
    synthesized = state.get("synthesized_claims", [])
    if synthesized:
        return synthesized

    fallback: list[SynthesizedClaim] = []
    for lane, claims in (
        ("left", state["left_claims"]),
        ("centrist", state["centrist_claims"]),
        ("right", state["right_claims"]),
        ("people", state["people_claims"]),
    ):
        for claim in claims:
            fallback.append(
                SynthesizedClaim(
                    text=claim.text,
                    source_ids=claim.source_ids,
                    asserted_by=[lane],
                    contradicted_by=[],
                    confidence=0.50,
                    category="unique_insight",
                )
            )
    return fallback


def cross_check_facts_agent(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Run fact checks for all claims and return structured verdicts."""
    infosphere_sources = runtime_infosphere_sources(state, config)
    language = runtime_language(state, config)
    fact_sources = web_searcher(state, "fact", infosphere_sources["fact"])
    all_context_sources = (
        state["left_sources"]
        + state["centrist_sources"]
        + state["right_sources"]
        + state["people_sources"]
        + fact_sources
    )
    context_sources = _dedupe_sources_by_url(all_context_sources)

    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in context_sources
    )
    synthesized_claims = _synthesized_claims_for_fact_check(state)
    claims = [
        Claim(text=item.text, source_ids=item.source_ids)
        for item in synthesized_claims
    ]
    logger.info(
        "Fact-check: context_sources=%d fact_sources=%d claims=%d",
        len(context_sources),
        len(fact_sources),
        len(claims),
    )
    for idx, claim in enumerate(claims, start=1):
        sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
        logger.debug(
            "Fact-check input claim %d/%d: %s (Sources: %s)",
            idx,
            len(claims),
            claim.text,
            sources,
        )
    claims_block = "\n".join(
        (
            f"- {item.text} "
            f"(Category: {item.category}; Cross-lane confidence: {item.confidence:.2f}; "
            f"Asserted by: {', '.join(item.asserted_by) or 'none'}; "
            f"Contradicted by: {', '.join(item.contradicted_by) or 'none'}; "
            f"Sources: {', '.join(item.source_ids) if item.source_ids else 'none'})"
        )
        for item in synthesized_claims
    )
    claims_count = len(claims)
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources["fact"]
    )
    response_language = "Polish" if language == "polish" else "English"
    model_name = get_model("cross_check_facts")

    data = invoke_structured_chain(
        schema=FactCheckOutput,
        system_prompt="You are a meticulous fact-checker who only uses the provided sources.",
        human_prompt=(
            "Sources:\n{source_block}\n\n"
            "Claims:\n{claims_block}\n\n"
            "Preferred fact-check references (use for methods; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Fact-check each claim strictly against the provided sources. "
            "Do not speculate or add outside knowledge. "
            "Use verdicts: TRUE, PARTIALLY_TRUE, CONTESTED, UNVERIFIED. "
            "TRUE means multiple independent sources confirm the claim. "
            "PARTIALLY_TRUE means the core claim is supported but important context is missing. "
            "CONTESTED means provided sources disagree or the claim is condition-dependent. "
            "UNVERIFIED means evidence is insufficient in the provided sources. "
            "Write the rationale in {response_language}. Keep the verdict labels exactly as specified.\n"
            "Output requirements:\n"
            "- Return a JSON object with key `results`.\n"
            "- Return exactly {claims_count} items in `results` (one per claim).\n"
            "- `claim_text` should correspond to one input claim text (minor wording differences are acceptable).\n"
            "- Include confidence from 0.0 to 1.0.\n"
            "- If evidence is insufficient, still return that claim with verdict `UNVERIFIED` and rationale "
            "'Insufficient evidence in provided sources'.\n"
            "Return JSON exactly like:\n"
            '{{"results": [{{"claim_text": "...", "verdict": "UNVERIFIED", "confidence": 0.2, '
            '"rationale": "...", "supporting_source_ids": [], "contradicting_source_ids": []}}]}}'
        ),
        variables={
            "source_block": source_block,
            "claims_block": claims_block,
            "reference_block": reference_block,
            "response_language": response_language,
            "claims_count": claims_count,
        },
        temperature=0.0,
        model=model_name,
    )
    raw_results = list(getattr(data, "results", []))
    logger.debug("Fact-check: LLM raw results count=%d", len(raw_results))
    for idx, raw_item in enumerate(raw_results, start=1):
        logger.debug(
            "Fact-check raw result %d: claim_text=%r verdict=%r source_ids=%r",
            idx,
            getattr(raw_item, "claim_text", "")[:80],
            getattr(raw_item, "verdict", ""),
            getattr(raw_item, "source_ids", []),
        )

    context_source_ids = {source.id for source in context_sources}
    claims_by_text = {claim.text: claim for claim in claims if claim.text.strip()}
    results: List[FactCheckResult] = []
    seen_claims: set[str] = set()
    for item in raw_results:
        raw_claim_text = item.claim_text.strip()
        if not raw_claim_text:
            continue
        matched_claim_text = _find_best_claim_match(raw_claim_text, claims_by_text)
        if matched_claim_text is None or matched_claim_text in seen_claims:
            continue

        verdict = _normalize_verdict(item.verdict)
        confidence = _confidence_for_verdict(verdict, item.confidence)
        rationale = (
            item.rationale.strip() or "Insufficient evidence in provided sources."
        )
        supporting_sources = [
            sid.strip()
            for sid in (item.supporting_source_ids or item.source_ids)
            if isinstance(sid, str) and sid.strip() in context_source_ids
        ]
        contradicting_sources = [
            sid.strip()
            for sid in item.contradicting_source_ids
            if isinstance(sid, str) and sid.strip() in context_source_ids
        ]
        results.append(
            FactCheckResult(
                claim=Claim(text=matched_claim_text, source_ids=supporting_sources),
                verdict=verdict,
                confidence=confidence,
                rationale=rationale,
                supporting_sources=supporting_sources,
                contradicting_sources=contradicting_sources,
            )
        )
        seen_claims.add(matched_claim_text)

    logger.info(
        "Fact-check: normalized results=%d, unique input claims=%d",
        len(results),
        len(claims_by_text),
    )
    fallback_added = 0
    for claim in claims:
        if not claim.text.strip() or claim.text in seen_claims:
            if claim.text in seen_claims:
                logger.debug(
                    "Fact-check skipping already-seen claim: %s", claim.text[:80]
                )
            continue
        logger.debug("Fact-check adding fallback for unseen claim: %s", claim.text[:80])
        results.append(
            _fallback_result_for_claim(
                claim,
                rationale="No explicit support found in provided sources.",
            )
        )
        fallback_added += 1
    if fallback_added:
        logger.info(
            "Fact-check: added %d fallback verdicts for unmatched claims",
            fallback_added,
        )
    logger.info("Fact-check: produced %d verdicts", len(results))
    for idx, res in enumerate(results, start=1):
        sources = ", ".join(res.claim.source_ids) if res.claim.source_ids else "none"
        logger.debug(
            "Fact-check %d/%d: %s — %s (Sources: %s)",
            idx,
            len(results),
            res.verdict,
            res.claim.text,
            sources,
        )
    return {
        "fact_sources": fact_sources,
        "fact_checks": results,
    }
