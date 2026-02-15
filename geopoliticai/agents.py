"""Agent node definitions for the LangGraph pipeline."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Union

from geopoliticai.claims import build_claims
from geopoliticai.fact_check import fact_checker
from geopoliticai.governance import (
    arbiter_decide,
    extract_claims,
    referee,
    revise_analyses,
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


def ingest_request(state: PipelineState) -> PipelineState:
    return state


def build_research_plan_agent(state: PipelineState) -> PipelineState:
    return build_research_plan(state)


def search_left_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        "left_sources": web_searcher(state, "left", infosphere_sources["left"], seed_sources),
    }


def search_center_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        "centrist_sources": web_searcher(
            state, "centrist", infosphere_sources["centrist"], seed_sources
        ),
    }


def search_right_pool_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    return {
        **state,
        "right_sources": web_searcher(state, "right", infosphere_sources["right"], seed_sources),
    }


def left_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "left_claims": build_claims(
            state,
            "leftist",
            state["left_sources"],
            infosphere_sources["left"],
            language,
        ),
    }


def center_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "centrist_claims": build_claims(
            state,
            "centrist",
            state["centrist_sources"],
            infosphere_sources["centrist"],
            language,
        ),
    }


def right_analyst_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
) -> PipelineState:
    return {
        **state,
        "right_claims": build_claims(
            state,
            "right-wing",
            state["right_sources"],
            infosphere_sources["right"],
            language,
        ),
    }


def referee_agent(state: PipelineState) -> PipelineState:
    return referee(state)


def extract_claims_agent(state: PipelineState) -> PipelineState:
    return extract_claims(state)


def cross_check_facts_agent(
    state: PipelineState,
    infosphere_sources: dict[str, list[tuple[str, str]]],
    language: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
) -> PipelineState:
    with_fact_sources = {
        **state,
        "fact_sources": web_searcher(state, "fact", infosphere_sources["fact"], seed_sources),
    }
    return fact_checker(with_fact_sources, infosphere_sources["fact"], language)


def arbiter_decide_agent(state: PipelineState) -> PipelineState:
    return arbiter_decide(state)


def verify_more_agent(state: PipelineState) -> PipelineState:
    return verify_more(state)


def revise_analyses_agent(state: PipelineState) -> PipelineState:
    return revise_analyses(state)


def compose_final_agent(state: PipelineState, language: str) -> PipelineState:
    return summarizer_judge(state, language)


def make_supervisor_agent(
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

    def supervisor(state: PipelineState) -> PipelineState:
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

    return supervisor
