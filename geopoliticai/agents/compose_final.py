"""Compose the final synthesis from claims and fact-check results."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, field_validator

from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import PipelineState

logger = logging.getLogger(__name__)


class SynthesisOutput(BaseModel):
    """Structured output for the synthesis step."""

    synthesis: str = ""

    @field_validator("synthesis", mode="before")
    @classmethod
    def _coerce_synthesis_to_text(cls, value: Any) -> str:
        """Normalize non-string synthesis payloads into text."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            lines: list[str] = []
            for key, nested in value.items():
                label = key.replace("_", " ").strip().capitalize()
                if isinstance(nested, str):
                    lines.append(f"{label}: {nested}")
                else:
                    lines.append(f"{label}: {json.dumps(nested, ensure_ascii=False)}")
            return "\n".join(lines)
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return str(value)


def _looks_generic_synthesis(text: str) -> bool:
    """Heuristically detect templated or placeholder-heavy synthesis text."""
    lowered = text.lower()
    if not text.strip():
        return True
    placeholders = [" x ", " y ", " z ", " a ", " b ", " c "]
    generic_phrases = [
        "one claim states",
        "another claim asserts",
        "overall, while",
        "the claims presented",
        "some claims are robustly",
        "mixed evidence",
    ]
    if any(phrase in lowered for phrase in generic_phrases):
        return True
    if any(token in f" {lowered} " for token in placeholders):
        return True
    return False


def _fallback_synthesis(state: PipelineState, language: str) -> str:
    """Build a deterministic, claim-anchored synthesis if the LLM is too generic."""
    claims = state["left_claims"] + state["centrist_claims"] + state["right_claims"]
    bullets: list[str] = []
    for claim in claims[:4]:
        sources = ", ".join(claim.source_ids) if claim.source_ids else "none"
        bullets.append(f"- {claim.text} (Sources: {sources})")

    dispute = next(
        (
            r
            for r in state["fact_checks"]
            if r.verdict.upper() in {"MISLEADING", "FALSE", "PARTIALLY TRUE"}
        ),
        None,
    )
    if dispute:
        sources = ", ".join(dispute.claim.source_ids) if dispute.claim.source_ids else "none"
        bullets.append(
            f"- Dispute noted: {dispute.claim.text} — {dispute.verdict}. "
            f"{dispute.rationale} (Sources: {sources})"
        )

    if not bullets:
        if language == "polish":
            return "Brak wystarczających tez do stworzenia syntezy."
        return "Insufficient claims to synthesize."

    return "\n".join(bullets[:6])


def compose_final_agent(state: PipelineState, language: str) -> PipelineState:
    """Generate the final synthesis summary for the report."""
    if not (state["left_claims"] or state["centrist_claims"] or state["right_claims"]):
        logger.warning("Compose final: no analyst claims available for synthesis.")
    else:
        logger.info(
            "Compose final: claims counts left=%d centrist=%d right=%d.",
            len(state["left_claims"]),
            len(state["centrist_claims"]),
            len(state["right_claims"]),
        )
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in (
            state["left_claims"]
            + state["centrist_claims"]
            + state["right_claims"]
        )
    )
    true_checks = [r for r in state["fact_checks"] if r.verdict.upper() == "TRUE"]
    fact_block = "\n".join(
        f"- {r.verdict}: {r.claim.text} — {r.rationale}" for r in true_checks
    )
    true_claims_block = "\n".join(
        f"- {r.claim.text} (Sources: {', '.join(r.claim.source_ids) if r.claim.source_ids else 'none'})"
        for r in true_checks
    )
    response_language = "Polish" if language == "polish" else "English"

    data = invoke_structured_chain(
        schema=SynthesisOutput,
        system_prompt="You are a neutral methodological judge who prioritizes evidence quality.",
        human_prompt=(
            "All claims:\n{claims_block}\n\n"
            "Fact checks (TRUE only):\n{fact_block}\n\n"
            "Verified claims (TRUE):\n{true_claims_block}\n\n"
            "Task: Provide a synthesis that directly answers the user query using only verified (TRUE) claims. "
            "If no claims are TRUE, state that there is insufficient verified support.\n"
            "Requirements:\n"
            "- Write in {response_language}.\n"
            "- Answer the query directly in 2-4 sentences; if the query is a statement, provide a concise statement response.\n"
            "- Use only TRUE claims; do not include unverified content.\n"
            "- If no TRUE claims, explicitly say so.\n"
            "- Mention at least 2 concrete facts when available; if fewer exist, use what is available.\n"
            "- Include source IDs in parentheses when possible, e.g., (Sources: S1, S3).\n"
            "- Do not use placeholders like X/Y/Z/A/B or generic templates.\n"
            "Return a JSON object with exactly one key: synthesis (string)."
        ),
        variables={
            "claims_block": claims_block,
            "fact_block": fact_block,
            "true_claims_block": true_claims_block,
            "response_language": response_language,
        },
        temperature=0.2,
    )
    synthesis = data.synthesis.strip()
    logger.info("Compose final: received synthesis len=%d", len(synthesis))
    if _looks_generic_synthesis(synthesis):
        logger.warning("Compose final: generic synthesis detected, retrying with stricter prompt.")
        retry = invoke_structured_chain(
            schema=SynthesisOutput,
            system_prompt="You are a neutral methodological judge who prioritizes evidence quality.",
            human_prompt=(
                "All claims:\n{claims_block}\n\n"
                "Fact checks (TRUE only):\n{fact_block}\n\n"
                "Verified claims (TRUE):\n{true_claims_block}\n\n"
                "Task: Provide a synthesis that answers the user query using only verified (TRUE) claims. "
                "If no claims are TRUE, state that there is insufficient verified support.\n"
                "Requirements:\n"
                "- Write in {response_language}.\n"
                "- Answer the query directly in 2-4 sentences; if the query is a statement, provide a concise statement response.\n"
                "- Use only TRUE claims; do not include unverified content.\n"
                "- If no TRUE claims, explicitly say so.\n"
                "- Mention concrete facts when available; if fewer exist, use what is available.\n"
                "- Include source IDs in parentheses when possible.\n"
                "- Strictly avoid placeholders or templated prose.\n"
                "Return a JSON object with exactly one key: synthesis (string)."
            ),
            variables={
                "claims_block": claims_block,
                "fact_block": fact_block,
                "true_claims_block": true_claims_block,
                "response_language": response_language,
            },
            temperature=0.1,
        )
        synthesis = retry.synthesis.strip()
        if _looks_generic_synthesis(synthesis):
            logger.warning("Compose final: generic synthesis persists, using fallback.")
            synthesis = _fallback_synthesis(state, language)
    logger.info("Compose final: final synthesis len=%d", len(synthesis))

    return {**state, "synthesis": synthesis}
