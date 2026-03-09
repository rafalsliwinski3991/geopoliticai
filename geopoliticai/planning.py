"""Research planning nodes."""

from __future__ import annotations

from geopoliticai.models import PipelineState, ResearchPlan


def build_research_plan(state: PipelineState) -> PipelineState:
    query = state["query"].strip()
    plan = ResearchPlan(
        queries=[query, f"{query} key facts", f"{query} primary sources"],
        must_find=["latest developments", "primary-source confirmation"],
    )
    return {
        "research_plan": {
            "queries": plan.queries,
            "entities": plan.entities,
            "timeframe": plan.timeframe,
            "must_find": plan.must_find,
        }
    }
