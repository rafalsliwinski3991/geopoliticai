"""Graph construction and execution."""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from langgraph.graph import END, StateGraph

from geopoliticai.agents import (
    arbiter_decide_agent,
    build_research_plan_agent,
    center_analyst_agent,
    compose_final_agent,
    cross_check_facts_agent,
    extract_claims_agent,
    ingest_request,
    left_analyst_agent,
    make_supervisor_agent,
    referee_agent,
    revise_analyses_agent,
    right_analyst_agent,
    search_center_pool_agent,
    search_left_pool_agent,
    search_right_pool_agent,
    verify_more_agent,
)
from geopoliticai.config import get_infosphere_sources
from geopoliticai.governance import route_from_arbiter
from geopoliticai.models import PipelineState, Source


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = "english",
):
    language = "polish" if infosphere == "polish" else "english"
    infosphere_sources = get_infosphere_sources(infosphere)
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_request", ingest_request)
    graph.add_node("build_research_plan", build_research_plan_agent)
    graph.add_node(
        "search_left_pool",
        lambda state: search_left_pool_agent(state, infosphere_sources, seed_sources),
    )
    graph.add_node(
        "search_center_pool",
        lambda state: search_center_pool_agent(state, infosphere_sources, seed_sources),
    )
    graph.add_node(
        "search_right_pool",
        lambda state: search_right_pool_agent(state, infosphere_sources, seed_sources),
    )
    graph.add_node(
        "left_analyst", lambda state: left_analyst_agent(state, infosphere_sources, language)
    )
    graph.add_node(
        "center_analyst",
        lambda state: center_analyst_agent(state, infosphere_sources, language),
    )
    graph.add_node(
        "right_analyst",
        lambda state: right_analyst_agent(state, infosphere_sources, language),
    )
    graph.add_node("referee", referee_agent)
    graph.add_node("extract_claims", extract_claims_agent)
    graph.add_node(
        "cross_check_facts",
        lambda state: cross_check_facts_agent(
            state, infosphere_sources, language, seed_sources
        ),
    )
    graph.add_node("arbiter_decide", arbiter_decide_agent)
    graph.add_node("verify_more", verify_more_agent)
    graph.add_node("revise_analyses", revise_analyses_agent)
    graph.add_node("compose_final", lambda state: compose_final_agent(state, language))
    graph.add_node("supervisor", make_supervisor_agent(infosphere_sources, language))

    graph.set_entry_point("ingest_request")
    graph.add_edge("ingest_request", "build_research_plan")
    graph.add_edge("build_research_plan", "search_left_pool")
    graph.add_edge("search_left_pool", "left_analyst")
    graph.add_edge("left_analyst", "search_center_pool")
    graph.add_edge("search_center_pool", "center_analyst")
    graph.add_edge("center_analyst", "search_right_pool")
    graph.add_edge("search_right_pool", "right_analyst")
    graph.add_edge("right_analyst", "referee")
    graph.add_edge("referee", "extract_claims")
    graph.add_edge("extract_claims", "cross_check_facts")
    graph.add_edge("cross_check_facts", "arbiter_decide")
    graph.add_conditional_edges(
        "arbiter_decide",
        route_from_arbiter,
        {
            "EXECUTE": "compose_final",
            "ESCALATE": "compose_final",
            "HALT": "compose_final",
            "VERIFY": "verify_more",
            "REVISE": "revise_analyses",
        },
    )
    graph.add_edge("verify_more", "search_left_pool")
    graph.add_edge("revise_analyses", "referee")
    graph.add_edge("compose_final", "supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()


def run_pipeline(
    query: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = "english",
) -> str:
    app = build_graph(seed_sources, infosphere)
    initial_state: PipelineState = {
        "query": query,
        "language": "polish" if infosphere == "polish" else "english",
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "left_sources": [],
        "centrist_sources": [],
        "right_sources": [],
        "fact_sources": [],
        "fact_checks": [],
        "synthesis": "",
        "final_output": "",
        "research_plan": {"queries": [], "entities": [], "timeframe": "", "must_find": []},
        "referee_report": {
            "blocked": False,
            "issues": [],
            "unsupported_facts": [],
            "loaded_language": [],
            "required_verifications": [],
            "required_rewrites": [],
        },
        "extracted_claims": [],
        "decision": "EXECUTE",
        "decision_rationale": "",
        "verification_to_do": [],
        "rewrites_to_do": [],
        "loop_count": 0,
        "max_loops": 2,
    }
    result = app.invoke(initial_state)
    return result["final_output"]
