"""Graph construction and execution for the GeopoliticAI workflow."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from config import get_infosphere_sources
from models import (
    PipelineState,
    RefereeReport,
    build_initial_pipeline_state,
    normalize_language,
)
from nodes import (
    build_research_plan_step,
    center_analyst_agent,
    compose_final_agent,
    cross_check_facts_agent,
    extract_claims_for_verification,
    ingest_request,
    left_analyst_agent,
    people_analyst_agent,
    right_analyst_agent,
    run_referee_checks,
    search_center_pool,
    search_left_pool,
    search_people_pool,
    search_right_pool,
    summarize_referee_block,
    supervisor_step,
)

DEFAULT_INFOSPHERE = "english"
DEFAULT_REPORT_MODE = "full"
RECURSION_LIMIT = 25

# Conservative retry for LLM-heavy nodes: failures are expensive and usually
# need a backoff to clear (rate limits, transient model errors).
_LLM_RETRY = RetryPolicy(max_attempts=3, backoff_factor=2.0)
# Aggressive retry for IO-heavy search nodes: failures are cheap to retry
# and most are transient HTTP errors against Brave Search.
_SEARCH_RETRY = RetryPolicy(max_attempts=5, backoff_factor=0.5)


def _normalize_report_mode(report_mode: str) -> str:
    normalized = report_mode.strip().lower()
    if normalized not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")
    return normalized


def _route_after_referee(state: PipelineState) -> Literal["continue", "blocked"]:
    report = state.get("referee_report")
    if not isinstance(report, RefereeReport):
        return "blocked"
    return "blocked" if report.blocked else "continue"


def build_runtime_config(
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Build LangGraph runtime configuration shared by sync and stream entrypoints."""
    normalized_report_mode = _normalize_report_mode(report_mode)
    language = normalize_language(infosphere)
    configurable: dict[str, Any] = {
        "infosphere_sources": get_infosphere_sources(language),
        "language": language,
        "report_mode": normalized_report_mode,
    }
    if thread_id is not None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty when provided.")
        configurable["thread_id"] = thread_id
    return {"configurable": configurable, "recursion_limit": RECURSION_LIMIT}


def build_graph(
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Construct and compile the LangGraph pipeline."""
    _normalize_report_mode(report_mode)
    get_infosphere_sources(normalize_language(infosphere))
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_request", ingest_request)
    graph.add_node("build_research_plan", build_research_plan_step)
    graph.add_node("search_left_pool", search_left_pool, retry_policy=_SEARCH_RETRY)
    graph.add_node("search_center_pool", search_center_pool, retry_policy=_SEARCH_RETRY)
    graph.add_node("search_right_pool", search_right_pool, retry_policy=_SEARCH_RETRY)
    graph.add_node("search_people_pool", search_people_pool, retry_policy=_SEARCH_RETRY)
    graph.add_node("left_analyst", left_analyst_agent, retry_policy=_LLM_RETRY)
    graph.add_node("center_analyst", center_analyst_agent, retry_policy=_LLM_RETRY)
    graph.add_node("right_analyst", right_analyst_agent, retry_policy=_LLM_RETRY)
    graph.add_node("people_analyst", people_analyst_agent, retry_policy=_LLM_RETRY)
    graph.add_node("referee", run_referee_checks, retry_policy=_LLM_RETRY)
    graph.add_node(
        "referee_blocked_summary", summarize_referee_block, retry_policy=_LLM_RETRY
    )
    graph.add_node(
        "extract_claims", extract_claims_for_verification, retry_policy=_LLM_RETRY
    )
    graph.add_node("cross_check_facts", cross_check_facts_agent, retry_policy=_LLM_RETRY)
    graph.add_node("compose_final", compose_final_agent, retry_policy=_LLM_RETRY)
    graph.add_node("supervisor", supervisor_step)

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
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
    checkpointer: Any | None = None,
) -> str:
    """Execute the pipeline and return the final rendered report."""
    normalized_report_mode = _normalize_report_mode(report_mode)
    language = normalize_language(infosphere)

    # Reuse the module-level compiled graph; only recompile when the caller
    # supplied a checkpointer (the only configurable that changes the graph
    # itself rather than just per-run config).
    app = (
        build_graph(
            infosphere=infosphere,
            report_mode=normalized_report_mode,
            checkpointer=checkpointer,
        )
        if checkpointer is not None
        else graph
    )
    initial_state = build_initial_pipeline_state(
        query,
        language=language,
    )
    config = build_runtime_config(
        infosphere=infosphere,
        report_mode=normalized_report_mode,
        thread_id=thread_id,
    )
    result = app.invoke(initial_state, config=config)
    return str(result["final_output"])


graph = build_graph()
