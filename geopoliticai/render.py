"""Rendering utilities for pipeline output."""

from __future__ import annotations

from typing import Dict, List

from geopoliticai.models import Claim, FactCheckResult, PipelineState, Source


def render_sources(sources: List[Source]) -> str:
    lines = []
    for source in sources:
        lines.append(f"- [{source.id}] {source.title} ({source.url}) — {source.notes}")
    return "\n".join(lines)


def render_claims(claims: List[Claim]) -> str:
    lines = []
    for claim in claims:
        cite = ", ".join(claim.source_ids) if claim.source_ids else "no sources"
        lines.append(f"- {claim.text} (Sources: {cite})")
    return "\n".join(lines)


def render_reference_list(references: List[tuple[str, str]]) -> str:
    return "\n".join(f"- {name} ({url})" for name, url in references)


def render_fact_checks(results: List[FactCheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"- {result.verdict}: {result.claim.text} — {result.rationale}")
    return "\n".join(lines)


def merge_sources(state: PipelineState) -> List[Source]:
    dedup: Dict[str, Source] = {}
    for src in (
        state["left_sources"]
        + state["centrist_sources"]
        + state["right_sources"]
        + state["people_sources"]
        + state["fact_sources"]
    ):
        if src.url not in dedup:
            dedup[src.url] = src
    return list(dedup.values())
