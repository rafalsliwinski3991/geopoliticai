"""Summarizer stage for the pipeline."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import PipelineState

logger = logging.getLogger(__name__)


class SynthesisOutput(BaseModel):
    synthesis: str = ""


def summarizer_judge(state: PipelineState, language: str | None = None) -> PipelineState:
    logger.info("Summarizing: fact_checks=%d", len(state["fact_checks"]))
    claims_block = "\n".join(
        f"- {c.text} (Sources: {', '.join(c.source_ids) if c.source_ids else 'none'})"
        for c in (
            state["left_claims"]
            + state["centrist_claims"]
            + state["right_claims"]
        )
    )
    fact_block = "\n".join(
        f"- {r.verdict}: {r.claim.text} — {r.rationale}" for r in state["fact_checks"]
    )
    response_language = "Polish" if language == "polish" else "English"

    data = invoke_structured_chain(
        schema=SynthesisOutput,
        system_prompt="You are a neutral methodological judge who prioritizes evidence quality.",
        human_prompt=(
            "Claims:\n{claims_block}\n\n"
            "Fact checks:\n{fact_block}\n\n"
            "Task: Provide a neutral synthesis highlighting consensus, disputes, and strongest-supported conclusions. "
            "Write the synthesis in {response_language}."
        ),
        variables={
            "claims_block": claims_block,
            "fact_block": fact_block,
            "response_language": response_language,
        },
        temperature=0.2,
    )
    synthesis = data.synthesis.strip()
    return {**state, "synthesis": synthesis}
