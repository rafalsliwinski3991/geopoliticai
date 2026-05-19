"""Graph construction and execution for the GeopoliticAI workflow."""

from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from geopoliticai.config import get_infosphere_sources
from geopoliticai.models import (
    PipelineState,
    RefereeReport,
    build_initial_pipeline_state,
    normalize_language,
)
from geopoliticai.nodes import (
    build_research_plan_step,
    center_analyst_agent,
    compose_final_agent,
    cross_check_facts_agent,
    extract_claims_lane,
    fan_out_extract,
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

logger = logging.getLogger(__name__)

DEFAULT_INFOSPHERE = "english"
DEFAULT_REPORT_MODE = "full"


def _normalize_report_mode(report_mode: str) -> str:
    normalized = report_mode.strip().lower()
    if normalized not in {"compact", "full"}:
        raise ValueError("report_mode must be one of: compact, full.")
    return normalized


def _route_after_referee(state: PipelineState) -> str | list[Send]:
    """Route to the blocked summary node or fan out into per-lane extraction."""
    report = state.get("referee_report")
    if not isinstance(report, RefereeReport) or report.blocked:
        return "referee_blocked_summary"
    return fan_out_extract(state)


def build_runtime_config(
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    thread_id: str | None = None,
) -> dict[str, dict[str, Any]]:
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
    return {"configurable": configurable}


def build_checkpointer() -> Any:
    """Return a checkpointer suitable for the current environment.

    Uses ``PostgresSaver`` when ``DATABASE_URL`` is set and
    ``langgraph-checkpoint-postgres`` is installed; falls back to
    ``InMemorySaver`` otherwise. The Postgres import is local so the optional
    dependency isn't required for dev or for CI runs that do not exercise it.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return InMemorySaver()
    try:
        from langgraph.checkpoint.postgres import (
            PostgresSaver,  # type: ignore[import-not-found]
        )
    except ImportError:
        logger.warning(
            "DATABASE_URL set but langgraph-checkpoint-postgres not installed; "
            "falling back to InMemorySaver.",
        )
        return InMemorySaver()
    saver_cm = PostgresSaver.from_conn_string(db_url)
    saver = saver_cm.__enter__()
    try:
        saver.setup()
    except Exception:
        logger.exception("PostgresSaver.setup() failed; checkpoints may not persist.")
    return saver


def build_graph(
    infosphere: str = DEFAULT_INFOSPHERE,
    report_mode: str = DEFAULT_REPORT_MODE,
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Construct and compile the LangGraph pipeline.

    The topology is identical across infospheres — per-request language and
    source pools flow through ``configurable`` at invoke time. The
    ``infosphere``/``report_mode`` arguments are validated eagerly so misuse
    fails fast at construction.
    """
    _normalize_report_mode(report_mode)
    get_infosphere_sources(normalize_language(infosphere))
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_request", ingest_request)
    graph.add_node("build_research_plan", build_research_plan_step)
    graph.add_node("search_left_pool", search_left_pool)
    graph.add_node("search_center_pool", search_center_pool)
    graph.add_node("search_right_pool", search_right_pool)
    graph.add_node("search_people_pool", search_people_pool)
    graph.add_node("left_analyst", left_analyst_agent)
    graph.add_node("center_analyst", center_analyst_agent)
    graph.add_node("right_analyst", right_analyst_agent)
    graph.add_node("people_analyst", people_analyst_agent)
    graph.add_node("referee", run_referee_checks)
    graph.add_node("referee_blocked_summary", summarize_referee_block)
    graph.add_node("extract_claims_lane", extract_claims_lane)
    graph.add_node("cross_check_facts", cross_check_facts_agent)
    graph.add_node("compose_final", compose_final_agent)
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
        ["referee_blocked_summary", "extract_claims_lane"],
    )
    graph.add_edge("referee_blocked_summary", "supervisor")
    graph.add_edge("extract_claims_lane", "cross_check_facts")
    graph.add_edge("cross_check_facts", "compose_final")
    graph.add_edge("compose_final", "supervisor")
    graph.add_edge("supervisor", END)

    compile_kwargs: dict[str, Any] = {"name": "GeopoliticAI"}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return graph.compile(**compile_kwargs)


# Pre-built singletons per the plan (#4). The topology does not change with
# infosphere, so one compiled Pregel is reused — both names are exported as
# aliases for forward-compatibility if the graphs ever diverge.
graph = build_graph()
GRAPH_EN = graph
GRAPH_PL = graph


def get_compiled_graph(infosphere: str) -> Any:
    """Return the pre-built compiled graph for the given infosphere."""
    return GRAPH_PL if normalize_language(infosphere) == "polish" else GRAPH_EN


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

    app = (
        build_graph(
            infosphere=infosphere,
            report_mode=normalized_report_mode,
            checkpointer=checkpointer,
        )
        if checkpointer is not None
        else get_compiled_graph(infosphere)
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
