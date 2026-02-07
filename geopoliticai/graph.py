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
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> Callable[[PipelineState], PipelineState]:
    if language == "polish":
        labels = {
            "factual": "1. 🔎 Tło faktograficzne (z wyszukiwania)",
            "left": "2. 🔴 Perspektywa lewicowa",
            "centrist": "3. 🟡 Perspektywa centrowa",
            "right": "4. 🔵 Perspektywa prawicowa",
            "people": "5. 🟢 Perspektywa społeczna",
            "fact": "6. ✅ Wyniki weryfikacji faktów",
            "synthesis": "7. ⚖️ Synteza i najlepiej potwierdzone wnioski",
            "refs": "Preferowane źródła:",
        }
    else:
        labels = {
            "factual": "1. 🔎 Factual Background (from Web Searcher)",
            "left": "2. 🔴 Left Perspective",
            "centrist": "3. 🟡 Centrist Perspective",
            "right": "4. 🔵 Right Perspective",
            "people": "5. 🟢 People's Perspective",
            "fact": "6. ✅ Fact Check Results",
            "synthesis": "7. ⚖️ Synthesis & Best-Supported Conclusion",
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
        output.append(labels["people"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["people"]))
        output.append(render_claims(state["people_claims"]))
        output.append("")
        output.append(labels["fact"])
        output.append(labels["refs"])
        output.append(render_reference_list(infosphere_sources["fact"]))
        output.append(render_fact_checks(state["fact_checks"]))
        output.append("")
        output.append(labels["synthesis"])
        output.append(state["synthesis"])
        return {**state, "final_output": "\n".join(output)}

    return supervisor_finalize


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = "english",
):
    language = "polish" if infosphere == "polish" else "english"
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
        "people_searcher",
        lambda state: {
            **state,
            "people_sources": web_searcher(
                state, "people", infosphere_sources["people"], seed_sources
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
                state,
                "leftist",
                state["left_sources"],
                infosphere_sources["left"],
                language,
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
                language,
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
                language,
            ),
        },
    )
    graph.add_node(
        "people_expert",
        lambda state: {
            **state,
            "people_claims": build_claims(
                state,
                "people",
                state["people_sources"],
                infosphere_sources["people"],
                language,
            ),
        },
    )
    graph.add_node(
        "fact_checker",
        lambda state: fact_checker(state, infosphere_sources["fact"], language),
    )
    graph.add_node("summarizer_judge", lambda state: summarizer_judge(state, language))
    graph.add_node(
        "supervisor", _make_supervisor_finalize(infosphere_sources, language)
    )

    graph.set_entry_point("left_searcher")
    graph.add_edge("left_searcher", "left_expert")
    graph.add_edge("left_expert", "centrist_searcher")
    graph.add_edge("centrist_searcher", "centrist_expert")
    graph.add_edge("centrist_expert", "right_searcher")
    graph.add_edge("right_searcher", "right_expert")
    graph.add_edge("right_expert", "people_searcher")
    graph.add_edge("people_searcher", "people_expert")
    graph.add_edge("people_expert", "fact_searcher")
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
        "language": "polish" if infosphere == "polish" else "english",
        "left_claims": [],
        "centrist_claims": [],
        "right_claims": [],
        "people_claims": [],
        "left_sources": [],
        "centrist_sources": [],
        "right_sources": [],
        "people_sources": [],
        "fact_sources": [],
        "fact_checks": [],
        "synthesis": "",
        "final_output": "",
    }
    result = app.invoke(initial_state)
    return result["final_output"]
