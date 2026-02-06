"""Graph construction and execution."""

from __future__ import annotations

from typing import Dict, List, Optional, Union

from langgraph.graph import END, StateGraph

from geopoliticai.claims import centrist_expert, leftist_expert, right_expert
from geopoliticai.config import (
    CENTRIST_SOURCES,
    FACT_CHECK_SOURCES,
    LEFTIST_SOURCES,
    RIGHTIST_SOURCES,
)
from geopoliticai.fact_check import fact_checker
from geopoliticai.models import PipelineState, Source
from geopoliticai.render import (
    merge_sources,
    render_claims,
    render_fact_checks,
    render_reference_list,
    render_sources,
)
from geopoliticai.search import web_searcher
from geopoliticai.summarizer import summarizer_judge


def supervisor_finalize(state: PipelineState) -> PipelineState:
    output: List[str] = []
    output.append("1. \ud83d\udd0e Factual Background (from Web Searcher)")
    output.append(render_sources(merge_sources(state)))
    output.append("")
    output.append("2. \ud83d\udd34 Left Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(LEFTIST_SOURCES))
    output.append(render_claims(state["left_claims"]))
    output.append("")
    output.append("3. \ud83d\udfe1 Centrist Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(CENTRIST_SOURCES))
    output.append(render_claims(state["centrist_claims"]))
    output.append("")
    output.append("4. \ud83d\udd35 Right Perspective")
    output.append("Preferred references:")
    output.append(render_reference_list(RIGHTIST_SOURCES))
    output.append(render_claims(state["right_claims"]))
    output.append("")
    output.append("5. \u2705 Fact Check Results")
    output.append("Preferred references:")
    output.append(render_reference_list(FACT_CHECK_SOURCES))
    output.append(render_fact_checks(state["fact_checks"]))
    output.append("")
    output.append("6. \u2696\ufe0f Synthesis & Best-Supported Conclusion")
    output.append(state["synthesis"])
    return {**state, "final_output": "\n".join(output)}


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None
):
    graph = StateGraph(PipelineState)

    graph.add_node(
        "left_searcher",
        lambda state: {
            **state,
            "left_sources": web_searcher(state, "left", LEFTIST_SOURCES, seed_sources),
        },
    )
    graph.add_node(
        "centrist_searcher",
        lambda state: {
            **state,
            "centrist_sources": web_searcher(
                state, "centrist", CENTRIST_SOURCES, seed_sources
            ),
        },
    )
    graph.add_node(
        "right_searcher",
        lambda state: {
            **state,
            "right_sources": web_searcher(state, "right", RIGHTIST_SOURCES, seed_sources),
        },
    )
    graph.add_node(
        "fact_searcher",
        lambda state: {
            **state,
            "fact_sources": web_searcher(
                state, "fact", FACT_CHECK_SOURCES, seed_sources
            ),
        },
    )
    graph.add_node("left_expert", leftist_expert)
    graph.add_node("centrist_expert", centrist_expert)
    graph.add_node("right_expert", right_expert)
    graph.add_node("fact_checker", fact_checker)
    graph.add_node("summarizer_judge", summarizer_judge)
    graph.add_node("supervisor", supervisor_finalize)

    graph.set_entry_point("left_searcher")
    graph.add_edge("left_searcher", "left_expert")
    graph.add_edge("left_expert", "centrist_searcher")
    graph.add_edge("centrist_searcher", "centrist_expert")
    graph.add_edge("centrist_expert", "right_searcher")
    graph.add_edge("right_searcher", "right_expert")
    graph.add_edge("right_expert", "fact_searcher")
    graph.add_edge("fact_searcher", "fact_checker")
    graph.add_edge("fact_checker", "summarizer_judge")
    graph.add_edge("summarizer_judge", "supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()


def run_pipeline(
    query: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> str:
    app = build_graph(seed_sources)
    initial_state: PipelineState = {
        "query": query,
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
    }
    result = app.invoke(initial_state)
    return result["final_output"]
