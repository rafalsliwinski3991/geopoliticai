"""Render a concise final report for CLI output."""

from __future__ import annotations

import logging
from typing import Callable, List

from geopoliticai.models import PipelineState
from geopoliticai.render import merge_sources

logger = logging.getLogger(__name__)


def _split_direct_answer_and_details(synthesis: str) -> tuple[str, str]:
    """Extract direct answer and remaining rationale from synthesis text."""
    stripped = synthesis.strip()
    if not stripped:
        return "Unavailable.", ""

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return "Unavailable.", ""

    first = lines[0]
    if first.lower().startswith("short answer:") or first.lower().startswith("krotka odpowiedz:"):
        first = first.split(":", 1)[1].strip() if ":" in first else first
    rest = "\n".join(lines[1:]).strip()
    return first, rest


def _render_concise_sources(state: PipelineState) -> str:
    """Render only source id, title, and URL for readability."""
    sources = merge_sources(state)
    if not sources:
        return "- No sources collected."
    lines = [f"- [{src.id}] {src.title} ({src.url})" for src in sources]
    return "\n".join(lines)


def make_supervisor_step(
    _infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> Callable[[PipelineState], PipelineState]:
    """Return a callable that assembles a concise final report."""
    if language == "polish":
        question_label = "Pytanie:"
        answer_label = "Odpowiedz:"
        rationale_label = "Uzasadnienie:"
        facts_label = "Weryfikacja faktow:"
        sources_label = "Zrodla:"
    else:
        question_label = "Question:"
        answer_label = "Answer:"
        rationale_label = "Rationale:"
        facts_label = "Fact-check:"
        sources_label = "Sources:"

    def supervisor_step(state: PipelineState) -> PipelineState:
        lines: List[str] = []

        logger.info(
            "Supervisor assembling report: left_sources=%d centrist_sources=%d right_sources=%d people_sources=%d fact_sources=%d",
            len(state["left_sources"]),
            len(state["centrist_sources"]),
            len(state["right_sources"]),
            len(state["people_sources"]),
            len(state["fact_sources"]),
        )
        total_claims = (
            len(state["left_claims"])
            + len(state["centrist_claims"])
            + len(state["right_claims"])
            + len(state["people_claims"])
        )
        logger.info(
            "Supervisor claims: left=%d centrist=%d right=%d people=%d total=%d fact_checks=%d",
            len(state["left_claims"]),
            len(state["centrist_claims"]),
            len(state["right_claims"]),
            len(state["people_claims"]),
            total_claims,
            len(state["fact_checks"]),
        )
        short_answer, synthesis_details = _split_direct_answer_and_details(state["synthesis"])
        lines.append(f"{question_label} {state['query']}")
        lines.append("")
        lines.append(f"{answer_label} {short_answer}")
        lines.append("")
        lines.append(rationale_label)
        lines.append(synthesis_details if synthesis_details else short_answer)
        lines.append("")
        lines.append(
            f"{facts_label} {len(state['fact_checks'])} verdicts from "
            f"{len(state['fact_sources'])} sources."
        )
        lines.append("")
        lines.append(sources_label)
        lines.append(_render_concise_sources(state))

        final_report = "\n".join(lines)
        logger.debug(
            "Supervisor final report length: %d chars, combined_claims=%d, fact_checks=%d",
            len(final_report),
            total_claims,
            len(state["fact_checks"]),
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
        return {**state, "final_output": final_report}

    return supervisor_step
