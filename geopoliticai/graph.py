"""Graph construction and execution."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Union

from langgraph.graph import END, StateGraph

from geopoliticai.claims import build_claims
from geopoliticai.config import get_infosphere_sources
from geopoliticai.fact_check import fact_checker
from geopoliticai.governance import (
    arbiter_decide,
    extract_claims,
    referee,
    revise_analyses,
    route_from_arbiter,
    verify_more,
)
from geopoliticai.models import PipelineState, Source
from geopoliticai.planning import build_research_plan
from geopoliticai.render import (
    merge_sources,
    render_claims,
    render_fact_checks,
    render_reference_list,
    render_sources,
)
from geopoliticai.search import web_searcher
from geopoliticai.summarizer import summarizer_judge


def _make_supervisor_finalize(
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> Callable[[PipelineState], PipelineState]:
    if language == "polish":
        labels = {
            "factual": "1. 🔎 Tło faktograficzne (z wyszukiwania)",
            "left": "2. 🔴 Perspektywa lewicowa",
            "centrist": "3. 🟡 Perspektywa centrowa",
            "right": "4. 🔵 Perspektywa prawicowa",
            "fact": "5. ✅ Wyniki weryfikacji faktów",
            "synthesis": "6. ⚖️ Synteza i najlepiej potwierdzone wnioski",
            "decision": "7. 🧭 Decyzja arbitra",
            "refs": "Preferowane źródła:",
        }
    else:
        labels = {
            "factual": "1. 🔎 Factual Background (from Web Searcher)",
            "left": "2. 🔴 Left Perspective",
            "centrist": "3. 🟡 Centrist Perspective",
            "right": "4. 🔵 Right Perspective",
            "fact": "5. ✅ Fact Check Results",
            "synthesis": "6. ⚖️ Synthesis & Best-Supported Conclusion",
            "decision": "7. 🧭 Arbiter Decision",
            "refs": "Preferred references:",
        }

    def supervisor_finalize(state: PipelineState) -> PipelineState:
        output: List[str] = []
        output.append(labels["factual"])
        output.append(render_sources(merge_sources(state)))
        output.append("")
        output.append(labels["left"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["left"]))
        output.append(render_claims(state["left_claims"]))
        output.append("")
        output.append(labels["centrist"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["centrist"]))
        output.append(render_claims(state["centrist_claims"]))
        output.append("")
        output.append(labels["right"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["right"]))
        output.append(render_claims(state["right_claims"]))
        output.append("")
        output.append(labels["fact"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["fact"]))
        output.append(render_fact_checks(state["fact_checks"]))
        output.append("")
        output.append(labels["synthesis"])
        output.append(state["synthesis"])
        output.append("")
        output.append(labels["decision"])
        output.append(f"- {state['decision']}: {state['decision_rationale']}")
        return {**state, "final_output": "\n".join(output)}

    return supervisor_finalize


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = "english",
):
    language = "polish" if infosphere == "polish" else "english"
    infosphere_sources = get_infosphere_sources(infosphere)
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_request", lambda state: state)
    graph.add_node("build_research_plan", build_research_plan)

    graph.add_node(
        "search_left_pool",
        lambda state: {
            **state,
            "left_sources": web_searcher(
                state, "left", infosphere_sources["left"], seed_sources
            ),
        },
    )
    graph.add_node(
        "search_center_pool",
        lambda state: {
            **state,
            "centrist_sources": web_searcher(
                state, "centrist", infosphere_sources["centrist"], seed_sources
            ),
        },
    )
    graph.add_node(
        "search_right_pool",
        lambda state: {
            **state,
            "right_sources": web_searcher(
                state, "right", infosphere_sources["right"], seed_sources
            ),
        },
    )
    graph.add_node(
        "left_analyst",
        lambda state: {
            **state,
            "left_claims": build_claims(
                state,
                "leftist",
                state["left_sources"],
                infosphere_sources["left"],
                language,
            ),
        },
    )
    graph.add_node(
        "center_analyst",
        lambda state: {
            **state,
            "centrist_claims": build_claims(
                state,
                "centrist",
                state["centrist_sources"],
                infosphere_sources["centrist"],
                language,
            ),
        },
    )
    graph.add_node(
        "right_analyst",
        lambda state: {
            **state,
            "right_claims": build_claims(
                state,
                "right-wing",
                state["right_sources"],
                infosphere_sources["right"],
                language,
            ),
        },
    )
    graph.add_node("referee", referee)
    graph.add_node("extract_claims", extract_claims)
    def _cross_check_facts(state: PipelineState) -> PipelineState:
        with_fact_sources = {
            **state,
            "fact_sources": web_searcher(
                state, "fact", infosphere_sources["fact"], seed_sources
            ),
        }
        return fact_checker(with_fact_sources, infosphere_sources["fact"], language)

    graph.add_node("cross_check_facts", _cross_check_facts)
    graph.add_node("arbiter_decide", arbiter_decide)
    graph.add_node("verify_more", verify_more)
    graph.add_node("revise_analyses", revise_analyses)
    graph.add_node("compose_final", summarizer_judge)
    graph.add_node("supervisor", _make_supervisor_finalize(infosphere_sources, language))

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
