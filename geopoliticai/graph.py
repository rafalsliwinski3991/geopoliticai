"""Graph construction and execution."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Union

from langgraph.graph import END, StateGraph

from geopoliticai.claims import build_claims
from geopoliticai.config import get_infosphere_sources
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


def _make_supervisor_finalize(
    infosphere_sources: dict[str, list[tuple[str, str]]]
) -> Callable[[PipelineState], PipelineState]:
    def supervisor_finalize(state: PipelineState) -> PipelineState:
        output: List[str] = []
        output.append("1. \ud83d\udd0e Factual Background (from Web Searcher)")
        output.append(render_sources(merge_sources(state)))
        output.append("")
        output.append("2. \ud83d\udd34 Left Perspective")
        output.append("Preferred references:")
        output.append(render_reference_list(infosphere_sources["left"]))
        output.append(render_claims(state["left_claims"]))
        output.append("")
        output.append("3. \ud83d\udfe1 Centrist Perspective")
        output.append("Preferred references:")
        output.append(render_reference_list(infosphere_sources["centrist"]))
        output.append(render_claims(state["centrist_claims"]))
        output.append("")
        output.append("4. \ud83d\udd35 Right Perspective")
        output.append("Preferred references:")
        output.append(render_reference_list(infosphere_sources["right"]))
        output.append(render_claims(state["right_claims"]))
        output.append("")
        output.append("5. \u2705 Fact Check Results")
        output.append("Preferred references:")
        output.append(render_reference_list(infosphere_sources["fact"]))
        output.append(render_fact_checks(state["fact_checks"]))
        output.append("")
        output.append("6. \u2696\ufe0f Synthesis & Best-Supported Conclusion")
        output.append(state["synthesis"])
        return {**state, "final_output": "\n".join(output)}

    return supervisor_finalize


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = "english",
):
    infosphere_sources = get_infosphere_sources(infosphere)
    graph = StateGraph(PipelineState)

    graph.add_node(
        "left_searcher",
        lambda state: {
            **state,
            "left_sources": web_searcher(
                state, "left", infosphere_sources["left"], seed_sources
            ),
        },
    )
    graph.add_node(
        "centrist_searcher",
        lambda state: {
            **state,
            "centrist_sources": web_searcher(
                state, "centrist", infosphere_sources["centrist"], seed_sources
            ),
        },
    )
    graph.add_node(
        "right_searcher",
        lambda state: {
            **state,
            "right_sources": web_searcher(
                state, "right", infosphere_sources["right"], seed_sources
            ),
        },
    )
    graph.add_node(
        "fact_searcher",
        lambda state: {
            **state,
            "fact_sources": web_searcher(
                state, "fact", infosphere_sources["fact"], seed_sources
            ),
        },
    )
    graph.add_node(
        "left_expert",
        lambda state: {
            **state,
            "left_claims": build_claims(
                state, "leftist", state["left_sources"], infosphere_sources["left"]
            ),
        },
    )
    graph.add_node(
        "centrist_expert",
        lambda state: {
            **state,
            "centrist_claims": build_claims(
                state,
                "centrist",
                state["centrist_sources"],
                infosphere_sources["centrist"],
            ),
        },
    )
    graph.add_node(
        "right_expert",
        lambda state: {
            **state,
            "right_claims": build_claims(
                state,
                "right-wing",
                state["right_sources"],
                infosphere_sources["right"],
            ),
        },
    )
    graph.add_node(
        "fact_checker",
        lambda state: fact_checker(state, infosphere_sources["fact"]),
    )
    graph.add_node("summarizer_judge", summarizer_judge)
    graph.add_node("supervisor", _make_supervisor_finalize(infosphere_sources))

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
    infosphere: str = "english",
) -> str:
    app = build_graph(seed_sources, infosphere)
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
