"""Summarizer stage for the pipeline."""

from __future__ import annotations

import logging

from geopoliticai.llm import llm_json
from geopoliticai.models import PipelineState

logger = logging.getLogger(__name__)


def summarizer_judge(state: PipelineState, language: str | None = None) -> PipelineState:
    logger.info("Summarizing: fact_checks=%d", len(state["fact_checks"]))
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in (
            state["left_claims"]
            + state["centrist_claims"]
            + state["right_claims"]
            + state["people_claims"]
        )
    )
    fact_block = "\n".join(
        f"- {r.verdict}: {r.claim.text} — {r.rationale}" for r in state["fact_checks"]
    )
    response_language = "Polish" if language == "polish" else "English"
    user = f"""
Claims:
{claims_block}

Fact checks:
{fact_block}

Task: Provide a neutral synthesis highlighting consensus, disputes, and strongest-supported conclusions.
Write the synthesis in {response_language}.
Return JSON: {{"synthesis": "..."}}.
""".strip()

    data = llm_json(
        system="You are a neutral methodological judge who prioritizes evidence quality.",
        user=user,
    )
    synthesis = (data.get("synthesis") or "").strip()
    return {**state, "synthesis": synthesis}
