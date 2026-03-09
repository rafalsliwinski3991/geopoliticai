"""Graph construction and execution for the GeopoliticAI workflow."""

from __future__ import annotations

from functools import partial
from typing import Any, Dict, List, Literal, Optional, Union

from langgraph.graph import END, START, StateGraph

from agents import (
    center_analyst_agent,
    compose_final_agent,
    cross_check_facts_agent,
    left_analyst_agent,
    people_analyst_agent,
    right_analyst_agent,
)
from tools import (
    build_research_plan_step,
    extract_claims_for_verification,
    ingest_request,
    make_supervisor_step,
    run_referee_checks,
    search_center_pool,
    search_left_pool,
    search_people_pool,
    search_right_pool,
    summarize_referee_block,
)
from config import get_infosphere_sources
from models import PipelineState, Source, build_initial_pipeline_state, normalize_language

DEFAULT_INFOSPHERE = "english"
DEFAULT_REPORT_MODE = "full"


def _normalize_report_mode(report_mode: str) -> str:
    normalized = report_mode.strip().lower()
    if normalized not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")
    return normalized


def _route_after_referee(state: PipelineState) -> Literal["continue", "blocked"]:
    report = state.get("referee_report")
    if not isinstance(report, dict):
        return "blocked"
    return "blocked" if bool(report.get("blocked")) else "continue"


def build_graph(
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    checkpointer: Any | None = None,
):
    """Construct and compile the LangGraph pipeline."""
    normalized_report_mode = _normalize_report_mode(report_mode)
    language = normalize_language(infosphere)
    infosphere_sources = get_infosphere_sources(language)
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_request", ingest_request)
    graph.add_node("build_research_plan", build_research_plan_step)
    graph.add_node(
        "search_left_pool",
        partial(
            search_left_pool,
            infosphere_sources=infosphere_sources,
            seed_sources=seed_sources,
        ),
    )
    graph.add_node(
        "search_center_pool",
        partial(
            search_center_pool,
            infosphere_sources=infosphere_sources,
            seed_sources=seed_sources,
        ),
    )
    graph.add_node(
        "search_right_pool",
        partial(
            search_right_pool,
            infosphere_sources=infosphere_sources,
            seed_sources=seed_sources,
        ),
    )
    graph.add_node(
        "search_people_pool",
        partial(
            search_people_pool,
            infosphere_sources=infosphere_sources,
            seed_sources=seed_sources,
        ),
    )
    graph.add_node(
        "left_analyst",
        partial(
            left_analyst_agent,
            infosphere_sources=infosphere_sources,
            language=language,
        ),
    )
    graph.add_node(
        "center_analyst",
        partial(
            center_analyst_agent,
            infosphere_sources=infosphere_sources,
            language=language,
        ),
    )
    graph.add_node(
        "right_analyst",
        partial(
            right_analyst_agent,
            infosphere_sources=infosphere_sources,
            language=language,
        ),
    )
    graph.add_node(
        "people_analyst",
        partial(
            people_analyst_agent,
            infosphere_sources=infosphere_sources,
            language=language,
        ),
    )
    graph.add_node("referee", run_referee_checks)
    graph.add_node("referee_blocked_summary", summarize_referee_block)
    graph.add_node("extract_claims", extract_claims_for_verification)
    graph.add_node(
        "cross_check_facts",
        partial(
            cross_check_facts_agent,
            infosphere_sources=infosphere_sources,
            language=language,
            seed_sources=seed_sources,
        ),
    )
    graph.add_node("compose_final", partial(compose_final_agent, language=language))
    graph.add_node(
        "supervisor",
        make_supervisor_step(
            infosphere_sources,
            language,
            report_mode=normalized_report_mode,
        ),
    )

    graph.add_edge(START, "ingest_request")
    graph.add_edge("ingest_request", "build_research_plan")
    graph.add_edge("build_research_plan", "search_left_pool")
    graph.add_edge("build_research_plan", "search_center_pool")
    graph.add_edge("build_research_plan", "search_right_pool")
    graph.add_edge("build_research_plan", "search_people_pool")
    graph.add_edge("search_left_pool", "left_analyst")
    graph.add_edge("search_center_pool", "center_analyst")
    graph.add_edge("search_right_pool", "right_analyst")
    graph.add_edge("search_people_pool", "people_analyst")
    graph.add_edge("left_analyst", "referee")
    graph.add_edge("center_analyst", "referee")
    graph.add_edge("right_analyst", "referee")
    graph.add_edge("people_analyst", "referee")
    graph.add_conditional_edges(
        "referee",
        _route_after_referee,
        {
            "continue": "extract_claims",
            "blocked": "referee_blocked_summary",
        },
    )
    graph.add_edge("referee_blocked_summary", "supervisor")
    graph.add_edge("extract_claims", "cross_check_facts")
    graph.add_edge("cross_check_facts", "compose_final")
    graph.add_edge("compose_final", "supervisor")
    graph.add_edge("supervisor", END)

    if checkpointer is None:
        return graph.compile(name="GeopoliticAI")
    return graph.compile(checkpointer=checkpointer, name="GeopoliticAI")


def run_pipeline(
    query: str,
    seed_sources: Optional[Union[List[Source], Dict[str, List[Source]]]] = None,
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
    checkpointer: Any | None = None,
) -> str:
    """Execute the pipeline and return the final rendered report."""
    normalized_report_mode = _normalize_report_mode(report_mode)

    app = build_graph(
        seed_sources,
        infosphere,
        report_mode=normalized_report_mode,
        checkpointer=checkpointer,
    )
    initial_state = build_initial_pipeline_state(
        query,
        language=normalize_language(infosphere),
    )
    if thread_id is not None and not thread_id.strip():
        raise ValueError("thread_id must not be empty when provided.")

    config = (
        {"configurable": {"thread_id": thread_id}}
        if thread_id is not None
        else None
    )
    result = app.invoke(initial_state, config=config)
    return result["final_output"]


graph = build_graph()
