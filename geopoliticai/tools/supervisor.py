"""Render the final report without LLM post-processing."""

from __future__ import annotations

import logging
from typing import Callable, List

from geopoliticai.models import PipelineState
from geopoliticai.render import (
    merge_sources,
    render_claims,
    render_fact_checks,
    render_reference_list,
    render_sources,
)

logger = logging.getLogger(__name__)


def make_supervisor_step(
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> Callable[[PipelineState], PipelineState]:
    """Return a callable that assembles the final report deterministically."""
    if language == "polish":
        section_labels = {
            "factual": "1. 🔎 Tło faktograficzne (z wyszukiwania)",
            "left": "2. 🔴 Perspektywa lewicowa",
            "centrist": "3. 🟡 Perspektywa centrowa",
            "right": "4. 🔵 Perspektywa prawicowa",
            "fact": "5. ✅ Wyniki weryfikacji faktów",
            "synthesis": "6. ⚖️ Synteza i najlepiej potwierdzone wnioski",
            "all_claims": "7. 📚 Wszystkie tezy (zbiorczo)",
            "agent_role_prefix": "Rola agenta:",
            "left_role": "akcent na sprawy społeczne, nierówności, prawa pracownicze.",
            "centrist_role": "balans interesów, instytucje, pragmatyczne kompromisy.",
            "right_role": "suwerenność, bezpieczeństwo, tradycja, gospodarka rynkowa.",
            "fact_role": "weryfikacja tez na podstawie źródeł.",
            "sources_label": "Źródła użyte (wybrane):",
            "claims_label": "Tezy agenta:",
            "refs": "Preferowane źródła:",
        }
    else:
        section_labels = {
            "factual": "1. 🔎 Factual Background (from Web Searcher)",
            "left": "2. 🔴 Left Perspective",
            "centrist": "3. 🟡 Centrist Perspective",
            "right": "4. 🔵 Right Perspective",
            "fact": "5. ✅ Fact Check Results",
            "synthesis": "6. ⚖️ Synthesis & Best-Supported Conclusion",
            "all_claims": "7. 📚 All Claims (combined)",
            "agent_role_prefix": "Agent role:",
            "left_role": "focus on labor, inequality, and social welfare implications.",
            "centrist_role": "balance trade-offs, institutions, and pragmatic policy.",
            "right_role": "sovereignty, security, tradition, and market outcomes.",
            "fact_role": "verify claims against sources.",
            "sources_label": "Sources used (selected):",
            "claims_label": "Analyst claims:",
            "refs": "Preferred references:",
        }

    def supervisor_step(state: PipelineState) -> PipelineState:
        lines: List[str] = []

        logger.info(
            "Supervisor assembling report: left_sources=%d centrist_sources=%d right_sources=%d fact_sources=%d",
            len(state["left_sources"]),
            len(state["centrist_sources"]),
            len(state["right_sources"]),
            len(state["fact_sources"]),
        )
        total_claims = len(state["left_claims"]) + len(state["centrist_claims"]) + len(state["right_claims"])
        logger.info(
            "Supervisor claims: left=%d centrist=%d right=%d total=%d fact_checks=%d",
            len(state["left_claims"]),
            len(state["centrist_claims"]),
            len(state["right_claims"]),
            total_claims,
            len(state["fact_checks"]),
        )
        lines.append(section_labels["factual"])
        lines.append(render_sources(merge_sources(state)))
        lines.append("")

        lines.append(section_labels["left"])
        lines.append(f"{section_labels['agent_role_prefix']} {section_labels['left_role']}")
        lines.append(section_labels["refs"])
        lines.append(render_reference_list(infosphere_sources["left"]))
        lines.append(section_labels["sources_label"])
        lines.append(render_sources(state["left_sources"]))
        lines.append(section_labels["claims_label"])
        lines.append(render_claims(state["left_claims"]))
        lines.append("")

        lines.append(section_labels["centrist"])
        lines.append(f"{section_labels['agent_role_prefix']} {section_labels['centrist_role']}")
        lines.append(section_labels["refs"])
        lines.append(render_reference_list(infosphere_sources["centrist"]))
        lines.append(section_labels["sources_label"])
        lines.append(render_sources(state["centrist_sources"]))
        lines.append(section_labels["claims_label"])
        lines.append(render_claims(state["centrist_claims"]))
        lines.append("")

        lines.append(section_labels["right"])
        lines.append(f"{section_labels['agent_role_prefix']} {section_labels['right_role']}")
        lines.append(section_labels["refs"])
        lines.append(render_reference_list(infosphere_sources["right"]))
        lines.append(section_labels["sources_label"])
        lines.append(render_sources(state["right_sources"]))
        lines.append(section_labels["claims_label"])
        lines.append(render_claims(state["right_claims"]))
        lines.append("")

        lines.append(section_labels["fact"])
        lines.append(f"{section_labels['agent_role_prefix']} {section_labels['fact_role']}")
        lines.append(section_labels["refs"])
        lines.append(render_reference_list(infosphere_sources["fact"]))
        lines.append(render_fact_checks(state["fact_checks"]))
        lines.append("")

        lines.append(section_labels["synthesis"])
        lines.append(state["synthesis"])
        lines.append("")

        combined_claims = (
            [("Left", c) for c in state["left_claims"]]
            + [("Centrist", c) for c in state["centrist_claims"]]
            + [("Right", c) for c in state["right_claims"]]
        )
        lines.append(section_labels["all_claims"])
        labeled_lines = []
        for lane, claim in combined_claims:
            cite = ", ".join(claim.source_ids) if claim.source_ids else "no sources"
            labeled_lines.append(f"- [{lane}] {claim.text} (Sources: {cite})")
        lines.append("\n".join(labeled_lines))

        final_report = "\n".join(lines)
        logger.info(
            "Supervisor final report length: %d chars, combined_claims=%d, fact_checks=%d",
            len(final_report),
            len(combined_claims),
            len(state["fact_checks"]),
        )
        if combined_claims:
            sample = combined_claims[0][1].text[:120].replace("\n", " ")
            logger.info("Supervisor sample claim: %s", sample)
        return {**state, "final_output": final_report}

    return supervisor_step
