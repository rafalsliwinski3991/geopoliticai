"""Render a concise final report for CLI output."""

import logging
import re
from collections import Counter
from typing import Any, Callable, List

from langchain_core.runnables import RunnableConfig

from geopoliticai.models import Claim, PipelineState, Source
from geopoliticai.nodes.runtime_config import runtime_language, runtime_report_mode
from geopoliticai.render import merge_sources

logger = logging.getLogger(__name__)
VERDICT_ORDER = ("TRUE", "PARTIALLY TRUE", "MISLEADING", "FALSE")
MAX_COMPACT_RATIONALE_BULLETS = 3
MAX_COMPACT_SOURCE_ITEMS = 5
MAX_BULLET_CHARS = 220
CONSENSUS_NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)\b")
_VERDICT_BADGE_PL = {
    "TRUE": "PRAWDA ✓",
    "PARTIALLY TRUE": "CZĘŚCIOWO PRAWDA ~",
    "MISLEADING": "MYLĄCE ?",
    "FALSE": "FAŁSZ ✗",
}
_VERDICT_BADGE_EN = {
    "TRUE": "TRUE ✓",
    "PARTIALLY TRUE": "PARTIALLY TRUE ~",
    "MISLEADING": "MISLEADING ?",
    "FALSE": "FALSE ✗",
}


def _split_direct_answer_and_details(synthesis: str) -> tuple[str, str]:
    """Extract direct answer and remaining rationale from synthesis text."""
    stripped = synthesis.strip()
    if not stripped:
        return "Unavailable.", ""

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return "Unavailable.", ""

    first = lines[0]
    if first.lower().startswith("short answer:") or first.lower().startswith(
        "krotka odpowiedz:"
    ):
        first = first.split(":", 1)[1].strip() if ":" in first else first
    rest = "\n".join(lines[1:]).strip()
    return first, rest


def _truncate_text(text: str, max_chars: int = MAX_BULLET_CHARS) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _extract_reason_bullets(text: str, *, max_items: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    lines = []
    for raw_line in stripped.splitlines():
        cleaned = raw_line.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lstrip("-* ").strip()
        if cleaned:
            lines.append(cleaned)
    if len(lines) <= 1:
        lines = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", stripped)
            if part.strip()
        ]

    bullets: list[str] = []
    for line in lines:
        normalized = _truncate_text(line)
        if not normalized:
            continue
        if normalized in bullets:
            continue
        bullets.append(normalized)
        if len(bullets) >= max_items:
            break
    return bullets


def _render_sources(state: PipelineState, *, max_items: int | None = None) -> str:
    """Render only source id, title, and URL for readability."""
    sources = merge_sources(state)
    if not sources:
        return "- No sources collected."
    selected = sources if max_items is None else sources[:max_items]
    lines = [f"- [{src.id}] {src.title} ({src.url})" for src in selected]
    if max_items is not None and len(sources) > max_items:
        lines.append(f"- ... {len(sources) - max_items} additional sources omitted")
    return "\n".join(lines)


def _fact_verdict_counts(state: PipelineState) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in state["fact_checks"]:
        verdict = item.verdict.strip().upper()
        counts[verdict] += 1
    return counts


def _infer_consensus_entity(state: PipelineState) -> str:
    """Infer likely top entity from TRUE/PARTIALLY TRUE fact-check claims."""
    claim_texts = [
        item.claim.text
        for item in state["fact_checks"]
        if item.verdict.strip().upper() in {"TRUE", "PARTIALLY TRUE"}
    ]
    if len(claim_texts) < 2:
        return ""

    entities: Counter[str] = Counter()
    for text in claim_texts:
        for name in CONSENSUS_NAME_PATTERN.findall(text):
            entities[name] += 1
    if not entities:
        return ""

    best_name, best_count = entities.most_common(1)[0]
    return best_name if best_count >= 2 else ""


def _build_verdict_lookup(state: PipelineState) -> dict[str, str]:
    """Return claim text → upper-cased verdict from fact_checks."""
    return {
        fc.claim.text.strip(): fc.verdict.strip().upper()
        for fc in state["fact_checks"]
        if fc.claim.text.strip()
    }


def _render_lane_claims(
    claims: List[Claim],
    verdict_lookup: dict[str, str],
    badges: dict[str, str],
    source_lookup: dict[str, Source],
) -> list[str]:
    """Render every claim with its verdict badge and inline source links."""
    if not claims:
        return [
            "- (brak twierdzeń)" if badges is _VERDICT_BADGE_PL else "- (no claims)"
        ]
    lines = []
    for claim in claims:
        text = _truncate_text(claim.text)
        verdict = verdict_lookup.get(claim.text.strip(), "")
        badge = badges.get(verdict, "– ?") if verdict else "– ?"
        source_parts = []
        for sid in claim.source_ids:
            src = source_lookup.get(sid)
            if src:
                source_parts.append(f"[{src.title}]({src.url})")
        if source_parts:
            lines.append(f"- [{badge}] {text} — {', '.join(source_parts)}")
        else:
            lines.append(f"- [{badge}] {text}")
    return lines


def _warn_if_answer_conflicts_with_consensus(answer: str, state: PipelineState) -> None:
    consensus = _infer_consensus_entity(state)
    if not consensus:
        return
    if consensus.lower() in answer.lower():
        return
    logger.warning(
        "Supervisor: short answer may conflict with fact-check consensus. answer=%r consensus_entity=%r",
        answer,
        consensus,
    )


def make_supervisor_step(
    _infosphere_sources: dict[str, list[tuple[str, str]]] | None,
    language: str,
    report_mode: str = "full",
) -> Callable[[PipelineState], dict[str, Any]]:
    """Return a callable that assembles a compact or full report."""
    normalized_report_mode = report_mode.strip().lower()
    if normalized_report_mode not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")

    if language == "polish":
        question_label = "Pytanie:"
        answer_label = "Odpowiedz:"
        rationale_label = "Uzasadnienie:"
        compact_rationale_label = "Dlaczego:"
        facts_label = "Weryfikacja faktow:"
        compact_facts_label = "Podsumowanie fact-checku:"
        compact_sources_label = "Najwazniejsze zrodla:"
        claims_label = "Twierdzenia analitykow:"
        lane_labels = ("Lewica:", "Centrum:", "Prawica:", "Osoby:")
        badges = _VERDICT_BADGE_PL
    else:
        question_label = "Question:"
        answer_label = "Answer:"
        rationale_label = "Rationale:"
        compact_rationale_label = "Why:"
        facts_label = "Fact-check:"
        compact_facts_label = "Fact-check summary:"
        compact_sources_label = "Top sources:"
        claims_label = "Analysts' claims:"
        lane_labels = ("Left:", "Center:", "Right:", "People:")
        badges = _VERDICT_BADGE_EN

    def supervisor_step(state: PipelineState) -> dict[str, Any]:
        lines: List[str] = []
        total_claims = (
            len(state["left_claims"])
            + len(state["centrist_claims"])
            + len(state["right_claims"])
            + len(state["people_claims"])
        )
        merged_sources = merge_sources(state)
        source_lookup: dict[str, Source] = {src.id: src for src in merged_sources}
        logger.info(
            "Supervisor: assembling %s report claims=%d fact_checks=%d merged_sources=%d",
            normalized_report_mode,
            total_claims,
            len(state["fact_checks"]),
            len(merged_sources),
        )
        logger.info(
            "Supervisor: lane claims left=%d centrist=%d right=%d people=%d",
            len(state["left_claims"]),
            len(state["centrist_claims"]),
            len(state["right_claims"]),
            len(state["people_claims"]),
        )
        short_answer, synthesis_details = _split_direct_answer_and_details(
            state["synthesis"]
        )
        _warn_if_answer_conflicts_with_consensus(short_answer, state)
        verdict_counts = _fact_verdict_counts(state)

        lines.append(f"{question_label} {state['query']}")
        lines.append("")
        lines.append(f"{answer_label} {short_answer}")
        lines.append("")

        if normalized_report_mode == "compact":
            rationale_bullets = _extract_reason_bullets(
                synthesis_details or short_answer,
                max_items=MAX_COMPACT_RATIONALE_BULLETS,
            )
            lines.append(compact_rationale_label)
            if rationale_bullets:
                for bullet in rationale_bullets:
                    lines.append(f"- {bullet}")
            else:
                lines.append("- No additional rationale provided.")
            lines.append("")
            verdict_counts_summary = " ".join(
                f"{label}={verdict_counts.get(label, 0)}" for label in VERDICT_ORDER
            )
            lines.append(
                f"{compact_facts_label} {verdict_counts_summary} "
                f"(total={len(state['fact_checks'])}, sources={len(state['fact_sources'])})."
            )
            lines.append("")
            lines.append(compact_sources_label)
            lines.append(_render_sources(state, max_items=MAX_COMPACT_SOURCE_ITEMS))
        else:
            if synthesis_details:
                lines.append(rationale_label)
                lines.append(synthesis_details)
            lines.append("")
            verdict_lookup = _build_verdict_lookup(state)
            lane_pairs = [
                (lane_labels[0], state["left_claims"]),
                (lane_labels[1], state["centrist_claims"]),
                (lane_labels[2], state["right_claims"]),
                (lane_labels[3], state["people_claims"]),
            ]
            lines.append(claims_label)
            for lane_label, lane_claims in lane_pairs:
                lines.append("")
                lines.append(lane_label)
                lines.extend(
                    _render_lane_claims(
                        lane_claims, verdict_lookup, badges, source_lookup
                    )
                )
            lines.append("")
            lines.append(
                f"{facts_label} {len(state['fact_checks'])} verdicts from "
                f"{len(state['fact_sources'])} sources."
            )

        final_report = "\n".join(lines)
        logger.info(
            "Supervisor: final report ready len=%d chars",
            len(final_report),
        )
        if total_claims:
            first_claim = (
                state["left_claims"]
                + state["centrist_claims"]
                + state["right_claims"]
                + state["people_claims"]
            )[0]
            sample = first_claim.text.replace("\n", " ")
            logger.debug("Supervisor sample claim: %s", sample)
        return {"final_output": final_report}

    return supervisor_step


def supervisor_step(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Assemble the final report using LangGraph runtime configuration."""
    step = make_supervisor_step(
        None,
        runtime_language(state, config),
        report_mode=runtime_report_mode(config),
    )
    return step(state)
