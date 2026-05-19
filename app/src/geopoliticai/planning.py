"""Research planning nodes."""

from __future__ import annotations

from typing import Any

from geopoliticai.models import PipelineState, ResearchPlan


def build_research_plan(state: PipelineState) -> dict[str, Any]:
    """Create deterministic search queries from the normalized request."""
    query = state["query"].strip()
    plan = ResearchPlan(
        queries=[query, f"{query} key facts", f"{query} primary sources"],
        must_find=["latest developments", "primary-source confirmation"],
    )
    return {"research_plan": plan}
