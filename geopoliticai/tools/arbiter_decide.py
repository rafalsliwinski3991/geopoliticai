from __future__ import annotations

from geopoliticai.models import PipelineState


def decide_arbiter_outcome(state: PipelineState) -> PipelineState:
    if state["loop_count"] >= state["max_loops"] and (
        state["verification_to_do"] or state["rewrites_to_do"]
    ):
        return {
            **state,
            "decision": "ESCALATE",
            "decision_rationale": "Maximum verification loops reached.",
        }

    if state["verification_to_do"]:
        return {
            **state,
            "decision": "VERIFY",
            "decision_rationale": "Missing support for one or more claims.",
        }

    if state["rewrites_to_do"]:
        return {
            **state,
            "decision": "REVISE",
            "decision_rationale": "Loaded language detected in one or more claims.",
        }

    return {
        **state,
        "decision": "EXECUTE",
        "decision_rationale": "Referee checks passed.",
    }


def route_from_arbiter_decision(state: PipelineState) -> str:
    return state.get("decision", "EXECUTE")
