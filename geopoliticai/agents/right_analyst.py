from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from geopoliticai.llm import invoke_structured_chain
from geopoliticai.models import Claim, PipelineState


class RightClaimItem(BaseModel):
    text: str = ""
    source_ids: List[str] = Field(default_factory=list)


class RightClaimsOutput(BaseModel):
    claims: List[RightClaimItem] = Field(default_factory=list)


def right_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    source_block = "\n".join(
        f"{s.id}: {s.title} - {s.notes} ({s.url})" for s in state["right_sources"]
    )
    reference_block = "\n".join(
        f"- {name} ({url})" for name, url in infosphere_sources["right"]
    )
    response_language = "Polish" if language == "polish" else "English"

    output = invoke_structured_chain(
        schema=RightClaimsOutput,
        system_prompt="You are a political analyst who writes precise, source-grounded claims.",
        human_prompt=(
            "Query: {query}\n"
            "Response language: {response_language}\n\n"
            "Sources:\n{source_block}\n\n"
            "Preferred references (use for framing; do not invent citations):\n"
            "{reference_block}\n\n"
            "Task: Provide 3-5 analytically cautious claims from the perspective: right-wing.\n"
            "- Use only the sources provided.\n"
            "- Each claim must cite one or more source IDs."
        ),
        variables={
            "query": state["query"],
            "response_language": response_language,
            "source_block": source_block,
            "reference_block": reference_block,
        },
        temperature=0.2,
    )
    claims = [
        Claim(text=item.text.strip(), source_ids=[sid for sid in item.source_ids if isinstance(sid, str)])
        for item in output.claims
        if item.text.strip()
    ]
    return {**state, "right_claims": claims}
