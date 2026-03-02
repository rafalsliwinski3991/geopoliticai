"""Rendering utilities for pipeline output."""

from __future__ import annotations

import re
from typing import Dict, List

from geopoliticai.models import Claim, FactCheckResult, PipelineState, Source


def _clean_text(text: str, max_len: int = 220) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def render_sources(sources: List[Source], max_items: int = 10) -> str:
    if not sources:
        return "- No sources collected."
    lines = []
    for source in sources[:max_items]:
        lines.append(
            f"- [{source.id}] {_clean_text(source.title, 120)} ({source.url}) — {_clean_text(source.notes, 240)}"
        )
    if len(sources) > max_items:
        lines.append(f"- ... {len(sources) - max_items} additional sources omitted")
    return "\n".join(lines)


def render_claims(claims: List[Claim], max_items: int = 3) -> str:
    if not claims:
        return "- No claims extracted."
    lines = []
    for claim in claims[:max_items]:
        cite = ", ".join(claim.source_ids) if claim.source_ids else "no sources"
        lines.append(f"- {_clean_text(claim.text, 260)} (Sources: {cite})")
    if len(claims) > max_items:
        lines.append(f"- ... {len(claims) - max_items} additional claims omitted")
    return "\n".join(lines)


def render_reference_list(references: List[tuple[str, str]]) -> str:
    if not references:
        return "- No preferred references configured."
    return "\n".join(f"- {name} ({url})" for name, url in references)


def render_fact_checks(results: List[FactCheckResult]) -> str:
    if not results:
        return "- No fact-check verdicts were produced."
    lines = []
    for result in results:
        lines.append(
            f"- {result.verdict}: {_clean_text(result.claim.text, 220)} — {_clean_text(result.rationale, 220)}"
        )
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
