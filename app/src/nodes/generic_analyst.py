"""Shared implementation for ideology-specific analyst agents."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any, Callable, List, cast

from pydantic import BaseModel, Field, field_validator

from config import get_model
from llm import invoke_structured_chain
from models import Claim, PipelineState, Source

logger = logging.getLogger(__name__)
ANALYST_SOURCE_NOTE_CHARS = 220

LANE_ANALYTICAL_LENSES = {
    "left": (
        "You analyse political events through the lens of power, inequality, "
        "and structural change. Focus on who benefits, who bears the cost, "
        "historical patterns of exploitation, institutional power dynamics, "
        "and international solidarity or imperialism. Your job is not to recite "
        "leftist talking points; it is to surface structural factors that other "
        "perspectives may overlook."
    ),
    "centrist": (
        "You analyse political events through the lens of pragmatic trade-offs "
        "and institutional reform. Focus on evidence quality, policy feasibility, "
        "second-order effects, institutional capacity, stakeholder alignment, "
        "and precedent. Your job is not to be generically balanced; it is to find "
        "what works and what the evidence says, even when that is uncomfortable "
        "for all sides."
    ),
    "right": (
        "You analyse political events through the lens of individual agency, "
        "market mechanisms, and tradition. Focus on constitutional constraints, "
        "unintended consequences of intervention, moral hazard, national interest, "
        "cultural continuity, and fiscal discipline. Your job is not to recite "
        "conservative talking points; it is to surface constraints and risks that "
        "other perspectives may downplay."
    ),
    "people": (
        "You analyse political events through the lens of lived experience and "
        "public sentiment. Focus on how real people are affected, what public "
        "discourse reveals, generational divides, trust in institutions, and the "
        "gap between policy and reality. Your job is not to summarize social "
        "media; it is to ground abstract policy debates in human impact and "
        "popular understanding."
    ),
}

DOMAIN_GUIDANCE = {
    "geopolitics": "Consider alliances, deterrence, sovereignty, international law, regional security, and diplomatic leverage.",
    "economics": "Consider GDP impact, distributional effects, market response, inflation, fiscal cost, and incentives.",
    "social_policy": "Consider access, equity, household impact, implementation capacity, public trust, and unintended exclusion.",
    "military": "Consider capability, readiness, escalation risk, deterrence, logistics, rules of engagement, and civil-military constraints.",
    "technology": "Consider innovation incentives, platform power, security, privacy, supply chains, standards, and regulatory capacity.",
    "environment": "Consider emissions, adaptation, ecosystem impact, energy trade-offs, distributional costs, and long-term risk.",
}

ALL_LANES_REASONING_INSTRUCTION = (
    "For each claim, explain why this perspective reaches the conclusion: "
    "name the premises, values, trade-offs, or evidence that lead to this view. "
    "Do not just state a position. If the sources include evidence that "
    "contradicts this perspective's usual position, include that evidence too."
)


class GenericClaimItem(BaseModel):
    """Single analyst claim with source identifiers."""

    text: str = ""
    source_ids: List[str] = Field(default_factory=list)

    @field_validator("source_ids", mode="before")
    @classmethod
    def _coerce_source_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]


class GenericClaimsOutput(BaseModel):
    """Structured output for analyst claim generation."""

    claims: List[GenericClaimItem] = Field(default_factory=list)


def _extract_claims(items: List[GenericClaimItem]) -> List[Claim]:
    """Convert model claim items into validated Claim objects."""
    claims: List[Claim] = []
    for item in items:
        text = item.text.strip()
        if not text:
            continue
        source_ids = [
            sid.strip()
            for sid in item.source_ids
            if isinstance(sid, str) and sid.strip()
        ]
        if not source_ids:
            match = re.search(
                r"\b(?:according to|wed(?:ług|lug))\s+([A-Za-z]+\d+)\b",
                text,
                flags=re.IGNORECASE,
            )
            if match:
                source_ids = [match.group(1).upper()]
        claims.append(Claim(text=text, source_ids=source_ids))
    return claims


def _keep_claims_with_allowed_sources(
    claims: List[Claim],
    allowed_source_ids: set[str],
    *,
    log_label: str,
) -> List[Claim]:
    """Drop claims that cite IDs outside the lane's provided sources."""
    sanitized: List[Claim] = []
    for claim in claims:
        valid_ids: List[str] = []
        seen_ids: set[str] = set()
        for source_id in claim.source_ids:
            normalized = source_id.strip()
            if normalized in allowed_source_ids and normalized not in seen_ids:
                valid_ids.append(normalized)
                seen_ids.add(normalized)
        if not valid_ids:
            logger.debug(
                "%s analyst: dropped claim with invalid source_ids=%s text=%r",
                log_label,
                claim.source_ids,
                claim.text[:120],
            )
            continue
        sanitized.append(Claim(text=claim.text, source_ids=valid_ids))
    return sanitized


def _truncate_for_prompt(text: str, max_chars: int = ANALYST_SOURCE_NOTE_CHARS) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _render_source_for_prompt(source: Source) -> str:
    summary = _truncate_for_prompt(source.notes or source.title or "")
    return f"{source.id}: {source.title} - {summary} ({source.url})"


def _fallback_claims_from_sources(
    sources: List[Source], limit: int, *, language: str = "english"
) -> List[Claim]:
    """Build minimal claims directly from source notes when the LLM returns none."""
    according_to = "Według" if language == "polish" else "According to"
    claims: List[Claim] = []
    for src in sources[:limit]:
        snippet = _truncate_for_prompt(
            src.notes or src.title or "",
            max_chars=180,
        ).strip()
        if not snippet:
            continue
        text = f"{according_to} {src.id}, {snippet}"
        claims.append(Claim(text=text, source_ids=[src.id]))
    return claims


def _extract_research_domain(state_values: Mapping[str, Any]) -> str:
    """Read the optional research-plan domain from dataclasses or mappings."""
    research_plan = state_values.get("research_plan")
    if isinstance(research_plan, Mapping):
        domain = research_plan.get("domain", "")
    else:
        domain = getattr(research_plan, "domain", "")
    if not isinstance(domain, str):
        return ""
    return domain.strip().lower().replace("-", "_").replace(" ", "_")


def _domain_guidance(domain: str) -> str:
    """Return prompt guidance for a research domain, with a safe fallback."""
    if not domain:
        return (
            "No specific research domain was provided. Adapt the analytical lens "
            "to the query and avoid assuming a domain that is not supported by "
            "the sources."
        )
    guidance = DOMAIN_GUIDANCE.get(domain)
    if guidance:
        return f"Research domain: {domain}. {guidance}"
    return (
        f"Research domain: {domain}. Apply the lane's analytical lens to the "
        "domain-specific actors, incentives, institutions, and trade-offs visible "
        "in the sources."
    )


def _lane_lens(lane_key: str, ideology: str) -> str:
    """Return the lane-specific analytical lens, falling back safely."""
    return LANE_ANALYTICAL_LENSES.get(
        lane_key,
        (
            f"You analyse political events from the {ideology} perspective. "
            "Focus on the values, incentives, institutions, and trade-offs this "
            "perspective would treat as most important."
        ),
    )


def _analyst_system_prompt(lane_key: str, ideology: str) -> str:
    """Build the lane-specific analyst system prompt."""
    return (
        "You are a political analyst who writes precise, source-grounded claims.\n\n"
        f"{_lane_lens(lane_key, ideology)}"
    )


def generic_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
    *,
    lane_key: str,
    ideology: str,
    model_key: str,
    log_label: str,
    perspective_label: str,
    fallback_limit: int,
    invoke_chain: Callable[..., BaseModel] = invoke_structured_chain,
) -> dict[str, Any]:
    """Generate ideology-specific claims grounded in lane sources."""
    sources_key = f"{lane_key}_sources"
    claims_key = f"{lane_key}_claims"
    state_values = cast(Mapping[str, Any], state)
    sources = cast(list[Source], state_values[sources_key])
    allowed_source_id_set = {source.id for source in sources}
    source_block = "\n".join(_render_source_for_prompt(source) for source in sources)
    allowed_source_ids = ", ".join(source.id for source in sources) or "none"
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources[lane_key]
    )
    research_domain = _extract_research_domain(state_values)
    domain_guidance = _domain_guidance(research_domain)
    lane_lens = _lane_lens(lane_key, ideology)
    system_prompt = _analyst_system_prompt(lane_key, ideology)
    response_language = "Polish" if language == "polish" else "English"
    according_to = "Według" if language == "polish" else "According to"
    model_name = get_model(model_key)
    example_source_id = sources[0].id if sources else "S1"

    output = invoke_chain(
        schema=GenericClaimsOutput,
        system_prompt=system_prompt,
        human_prompt=(
            "Query: {query}\n"
            "Response language: {response_language}\n\n"
            "Analytical lens:\n{lane_lens}\n\n"
            "Domain guidance:\n{domain_guidance}\n\n"
            "Sources:\n{source_block}\n\n"
            "Preferred references (use for framing; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Provide 3-5 analytically cautious claims from the {perspective_label} perspective ({ideology}).\n"
            "- Use only the sources provided.\n"
            "- Never return an empty claims list. If 3-5 is not possible, return 1-3 claims.\n"
            "- If sources are descriptive, still extract factual claims in the form '{according_to} <ID>, ...'.\n"
            "- {reasoning_instruction}\n"
            "- Each claim must cite one or more source IDs.\n"
            "- Allowed source IDs: {allowed_source_ids}.\n"
            "Return JSON exactly like this example:\n"
            '{{"claims": [{{"text": "{according_to} {example_source_id}, ...", "source_ids": ["{example_source_id}"]}}]}}\n'
            'Never return {{"claims": []}}.'
        ),
        variables={
            "query": state["query"],
            "response_language": response_language,
            "according_to": according_to,
            "source_block": source_block,
            "reference_block": reference_block,
            "lane_lens": lane_lens,
            "domain_guidance": domain_guidance,
            "perspective_label": perspective_label,
            "ideology": ideology,
            "reasoning_instruction": ALL_LANES_REASONING_INSTRUCTION,
            "allowed_source_ids": allowed_source_ids,
            "example_source_id": example_source_id,
        },
        temperature=0.2,
        model=model_name,
    )
    initial_raw_claims = getattr(output, "claims", [])
    logger.debug(
        "%s analyst: initial raw output claims=%r", log_label, initial_raw_claims
    )
    claims = _keep_claims_with_allowed_sources(
        _extract_claims(initial_raw_claims),
        allowed_source_id_set,
        log_label=log_label,
    )

    if not claims:
        logger.info(
            "%s analyst: initial pass produced 0 claims from %d sources; retrying.",
            log_label,
            len(sources),
        )
        retry = invoke_chain(
            schema=GenericClaimsOutput,
            system_prompt=system_prompt,
            human_prompt=(
                "Query: {query}\n"
                "Response language: {response_language}\n\n"
                "Analytical lens:\n{lane_lens}\n\n"
                "Domain guidance:\n{domain_guidance}\n\n"
                "Sources:\n{source_block}\n\n"
                "Task: Provide 2-3 factual claims from the sources. "
                "If the sources are descriptive, still convert them into factual claims. "
                "{reasoning_instruction} "
                "Each claim must include non-empty text and one or more source IDs from: {allowed_source_ids}. "
                'Return JSON exactly like: {{"claims": [{{"text": "{according_to} {example_source_id}, ...", "source_ids": ["{example_source_id}"]}}]}}. '
                'Never return {{"claims": []}}.'
            ),
            variables={
                "query": state["query"],
                "response_language": response_language,
                "according_to": according_to,
                "lane_lens": lane_lens,
                "domain_guidance": domain_guidance,
                "source_block": source_block,
                "reasoning_instruction": ALL_LANES_REASONING_INSTRUCTION,
                "allowed_source_ids": allowed_source_ids,
                "example_source_id": example_source_id,
            },
            temperature=0.1,
            model=model_name,
        )
        retry_raw_claims = getattr(retry, "claims", [])
        logger.debug(
            "%s analyst: retry raw output claims=%r", log_label, retry_raw_claims
        )
        claims = _keep_claims_with_allowed_sources(
            _extract_claims(retry_raw_claims),
            allowed_source_id_set,
            log_label=log_label,
        )

        if not claims:
            previous_claims_block = (
                "\n".join(
                    f"- text={getattr(item, 'text', '')!r}, source_ids={getattr(item, 'source_ids', [])!r}"
                    for item in retry_raw_claims
                )
                or "[]"
            )
            repair = invoke_chain(
                schema=GenericClaimsOutput,
                system_prompt="You repair JSON outputs for schema compliance.",
                human_prompt=(
                    "Query: {query}\n"
                    "Response language: {response_language}\n\n"
                    "Sources:\n{source_block}\n\n"
                    "Task: Repair the previous output into valid non-empty JSON with key `claims`.\n"
                    "- Keep only source-grounded factual claims.\n"
                    "- Preserve or add the lane-specific reasoning required here: {reasoning_instruction}\n"
                    "- Use source IDs from: {allowed_source_ids}.\n"
                    "- At least 1 claim is required.\n"
                    "Previous output summary:\n{previous_claims_block}\n\n"
                    'Return JSON exactly like: {{"claims": [{{"text": "{according_to} {example_source_id}, ...", "source_ids": ["{example_source_id}"]}}]}}.\n'
                    'Never return {{"claims": []}}.'
                ),
                variables={
                    "query": state["query"],
                    "response_language": response_language,
                    "according_to": according_to,
                    "source_block": source_block,
                    "reasoning_instruction": ALL_LANES_REASONING_INSTRUCTION,
                    "allowed_source_ids": allowed_source_ids,
                    "previous_claims_block": previous_claims_block,
                    "example_source_id": example_source_id,
                },
                temperature=0.0,
                model=model_name,
            )
            repair_raw_claims = getattr(repair, "claims", [])
            logger.debug(
                "%s analyst: repair raw output claims=%r",
                log_label,
                repair_raw_claims,
            )
            claims = _keep_claims_with_allowed_sources(
                _extract_claims(repair_raw_claims),
                allowed_source_id_set,
                log_label=log_label,
            )

        if not claims:
            logger.info(
                "%s analyst: retry returned 0 claims; using source-note fallback.",
                log_label,
            )
            claims = _fallback_claims_from_sources(
                sources, limit=fallback_limit, language=language
            )

        if not claims:
            logger.warning(
                "%s analyst fallback empty; creating minimal claim from query.",
                log_label,
            )
            fallback_id = sources[0].id if sources else ""
            claims = [
                Claim(
                    text=(
                        f"Perspektywa {perspective_label}: {state['query']}"
                        if language == "polish"
                        else f"{perspective_label} perspective on: {state['query']}"
                    ),
                    source_ids=[fallback_id] if fallback_id else [],
                )
            ]

    logger.info("%s analyst: produced %d claims.", log_label, len(claims))
    for idx, claim in enumerate(claims, start=1):
        sources_text = ", ".join(claim.source_ids) if claim.source_ids else "none"
        logger.debug(
            "%s claim %d/%d: %s (Sources: %s)",
            log_label,
            idx,
            len(claims),
            claim.text,
            sources_text,
        )
    return {claims_key: claims}
