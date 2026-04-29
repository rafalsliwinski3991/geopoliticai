"""Cross-lane synthesis and quality gate for analyst claims."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field, field_validator

from config import get_model
from llm import invoke_structured_chain
from models import Claim, PipelineState, RefereeReport, SynthesizedClaim
from nodes.referee import LOADED_TERMS

logger = logging.getLogger(__name__)

LANE_KEYS = ("left", "centrist", "right", "people")
SYNTHESIS_CATEGORIES = {"consensus", "contested", "unique_insight"}
CONFIDENCE_BY_LANE_COUNT = {
    4: 0.95,
    3: 0.85,
    2: 0.70,
    1: 0.50,
}


class SynthesizedClaimItem(BaseModel):
    """Structured output item for cross-lane claim synthesis."""

    text: str = ""
    source_ids: list[str] = Field(default_factory=list)
    asserted_by: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)
    category: Literal["consensus", "contested", "unique_insight"] | str = (
        "unique_insight"
    )

    @field_validator("source_ids", "asserted_by", "contradicted_by", mode="before")
    @classmethod
    def _coerce_string_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]


class SynthesizedClaimsOutput(BaseModel):
    """Structured output for synthesized claims."""

    claims: list[SynthesizedClaimItem] = Field(default_factory=list)


def _claim_pairs(state: PipelineState) -> list[tuple[str, Claim]]:
    """Return all lane claims tagged with their lane."""
    return [
        (lane, claim)
        for lane in LANE_KEYS
        for claim in state[f"{lane}_claims"]  # type: ignore[literal-required]
    ]


def _loaded_language_patterns() -> list[re.Pattern[str]]:
    """Build loaded-language regexes that also catch simple word variants."""
    patterns: list[re.Pattern[str]] = []
    for term in LOADED_TERMS:
        escaped_words = [re.escape(part) for part in term.split()]
        if not escaped_words:
            continue
        escaped_words[-1] = f"{escaped_words[-1]}\\w*"
        patterns.append(
            re.compile(r"\b" + r"\s+".join(escaped_words) + r"\b", re.IGNORECASE)
        )
    return patterns


def _find_loaded_claims(claims: Iterable[Claim]) -> list[str]:
    """Return claim texts containing prohibited loaded language."""
    patterns = _loaded_language_patterns()
    loaded: list[str] = []
    for claim in claims:
        if any(pattern.search(claim.text) for pattern in patterns):
            loaded.append(claim.text)
    return loaded


def _normalize_lane(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "center":
        return "centrist"
    return normalized if normalized in LANE_KEYS else ""


def _normalize_category(value: str, asserted_by: list[str], contradicted_by: list[str]) -> str:
    category = value.strip().lower()
    if category not in SYNTHESIS_CATEGORIES:
        if contradicted_by:
            return "contested"
        if len(asserted_by) >= 2:
            return "consensus"
        return "unique_insight"
    return category


def _confidence_for(asserted_by: list[str], contradicted_by: list[str]) -> float:
    """Calibrate confidence from cross-lane support and contradiction."""
    if contradicted_by:
        return 0.40
    return CONFIDENCE_BY_LANE_COUNT.get(len(set(asserted_by)), 0.50)


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        deduped.append(normalized)
        seen.add(normalized)
    return deduped


def _normalize_synthesized_items(
    raw_items: list[SynthesizedClaimItem],
    *,
    valid_source_ids: set[str],
) -> list[SynthesizedClaim]:
    """Convert model output to validated synthesized claims."""
    claims: list[SynthesizedClaim] = []
    seen_texts: set[str] = set()
    for item in raw_items:
        text = " ".join(item.text.split())
        if not text or text.lower() in seen_texts:
            continue

        asserted_by = _dedupe_preserving_order(
            lane for lane in (_normalize_lane(raw) for raw in item.asserted_by) if lane
        )
        if not asserted_by:
            continue
        contradicted_by = _dedupe_preserving_order(
            lane
            for lane in (_normalize_lane(raw) for raw in item.contradicted_by)
            if lane and lane not in asserted_by
        )
        source_ids = _dedupe_preserving_order(
            sid for sid in item.source_ids if sid.strip() in valid_source_ids
        )
        category = _normalize_category(item.category, asserted_by, contradicted_by)
        claims.append(
            SynthesizedClaim(
                text=text,
                source_ids=source_ids,
                asserted_by=asserted_by,
                contradicted_by=contradicted_by,
                confidence=_confidence_for(asserted_by, contradicted_by),
                category=category,  # type: ignore[arg-type]
            )
        )
        seen_texts.add(text.lower())
    return claims


def _fallback_synthesis(
    state: PipelineState, cleaned_claims: dict[str, list[Claim]] | None = None
) -> list[SynthesizedClaim]:
    """Build deterministic synthesized claims when the LLM is unavailable."""
    grouped: dict[str, dict[str, Any]] = {}
    claim_pairs = (
        [(lane, claim) for lane, claims in cleaned_claims.items() for claim in claims]
        if cleaned_claims is not None
        else _claim_pairs(state)
    )
    for lane, claim in claim_pairs:
        if not claim.source_ids:
            continue
        normalized = " ".join(claim.text.lower().split())
        if not normalized:
            continue
        bucket = grouped.setdefault(
            normalized,
            {
                "text": claim.text,
                "source_ids": [],
                "asserted_by": [],
            },
        )
        bucket["source_ids"].extend(claim.source_ids)
        bucket["asserted_by"].append(lane)

    synthesized: list[SynthesizedClaim] = []
    for bucket in grouped.values():
        asserted_by = _dedupe_preserving_order(bucket["asserted_by"])
        source_ids = _dedupe_preserving_order(bucket["source_ids"])
        category = "consensus" if len(asserted_by) >= 2 else "unique_insight"
        synthesized.append(
            SynthesizedClaim(
                text=bucket["text"],
                source_ids=source_ids,
                asserted_by=asserted_by,
                contradicted_by=[],
                confidence=_confidence_for(asserted_by, []),
                category=category,  # type: ignore[arg-type]
            )
        )
    return synthesized


def _render_lane_claims_for_prompt(state: PipelineState) -> str:
    """Render lane claims with source IDs for the synthesis prompt."""
    lines: list[str] = []
    for lane in LANE_KEYS:
        lines.append(f"{lane}:")
        claims = state[f"{lane}_claims"]  # type: ignore[literal-required]
        if not claims:
            lines.append("- none")
            continue
        for claim in claims:
            sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
            lines.append(f"- {claim.text} (Sources: {sources})")
    return "\n".join(lines)


def _source_ids_by_lane(state: PipelineState) -> dict[str, set[str]]:
    source_ids: dict[str, set[str]] = {}
    for lane in LANE_KEYS:
        sources = state[f"{lane}_sources"]  # type: ignore[literal-required]
        source_ids[lane] = {source.id for source in sources}
    return source_ids


def _clean_claims_by_source(state: PipelineState) -> dict[str, list[Claim]]:
    """Keep only claims with valid in-lane source IDs."""
    source_ids = _source_ids_by_lane(state)
    cleaned: dict[str, list[Claim]] = defaultdict(list)
    for lane, claim in _claim_pairs(state):
        valid_ids = [
            sid for sid in _dedupe_preserving_order(claim.source_ids) if sid in source_ids[lane]
        ]
        if valid_ids:
            cleaned[lane].append(Claim(text=claim.text, source_ids=valid_ids))
    return dict(cleaned)


def synthesize_perspectives_agent(state: PipelineState) -> dict[str, Any]:
    """Synthesize analyst claims, detect disagreements, and run a quality gate."""
    all_claims = [claim for _, claim in _claim_pairs(state)]
    cleaned = _clean_claims_by_source(state)
    clean_claims = [claim for claims in cleaned.values() for claim in claims]
    unsupported = [claim.text for claim in all_claims if not claim.source_ids]
    loaded = _find_loaded_claims(all_claims)
    has_some_supported = bool(clean_claims)
    report = RefereeReport(
        blocked=bool(loaded) or not has_some_supported,
        unsupported_facts=unsupported,
        loaded_language=loaded,
    )
    if report.blocked:
        return {
            "left_claims": cleaned.get("left", []),
            "centrist_claims": cleaned.get("centrist", []),
            "right_claims": cleaned.get("right", []),
            "people_claims": cleaned.get("people", []),
            "referee_report": report,
            "synthesized_claims": [],
        }

    valid_source_ids = {
        source_id for lane_ids in _source_ids_by_lane(state).values() for source_id in lane_ids
    }
    claims_block = _render_lane_claims_for_prompt(state)
    try:
        data = invoke_structured_chain(
            schema=SynthesizedClaimsOutput,
            system_prompt=(
                "You synthesize political analyst claims across perspectives. "
                "Detect consensus, contradiction, and unique insights without adding outside facts."
            ),
            human_prompt=(
                "User query: {query}\n\n"
                "Lane claims:\n{claims_block}\n\n"
                "Task:\n"
                "- Combine equivalent claims across lanes into one item.\n"
                "- Mark `asserted_by` with lanes that support the item.\n"
                "- Mark `contradicted_by` with lanes that directly disagree.\n"
                "- Use category: consensus, contested, or unique_insight.\n"
                "- Use only the source IDs present in the lane claims.\n"
                "- Keep claim text factual and suitable for downstream fact-checking.\n"
                "Return JSON with key `claims`."
            ),
            variables={
                "query": state["query"],
                "claims_block": claims_block,
            },
            temperature=0.0,
            model=get_model("synthesize_perspectives"),
        )
        synthesized = _normalize_synthesized_items(
            list(getattr(data, "claims", [])),
            valid_source_ids=valid_source_ids,
        )
    except Exception as exc:
        logger.warning(
            "Synthesize perspectives: LLM synthesis failed, using fallback: %s", exc
        )
        synthesized = []

    if not synthesized:
        synthesized = _fallback_synthesis(state, cleaned)

    logger.info(
        "Synthesize perspectives: produced %d synthesized claims from %d lane claims",
        len(synthesized),
        len(all_claims),
    )
    return {
        "left_claims": cleaned.get("left", []),
        "centrist_claims": cleaned.get("centrist", []),
        "right_claims": cleaned.get("right", []),
        "people_claims": cleaned.get("people", []),
        "referee_report": report,
        "synthesized_claims": synthesized,
    }
