"""Run one deep research turn and hold its result to the agent's hard rules."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import StreamWriter

from agents.deep_expert.config import LIMITS
from agents.deep_expert.consts.progress import PLANNING_PROGRESS
from agents.deep_expert.graph import (
    NO_CHECKPOINTER_CONFIG,
    SHIPPABLE_VERDICTS,
    build_graph,
)
from agents.deep_expert.prompts import DEEP_ANSWER_RUBRIC
from agents.deep_expert.state import ResearchRun
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    ResearchLimitError,
)
from tracing import start_span

# Same pattern as `evals/helpers/judge.py::MARKDOWN_LINK_URL`; src never imports evals.
MARKDOWN_LINK_URL = re.compile(r"\]\((https?://[^)\s]+)\)")
logger = logging.getLogger(__name__)


async def research(query: str, writer: StreamWriter) -> str:
    """Research `query` in depth and return the finished, checked answer.

    A `deep_research` span records whether the turn ran out of searches or
    time (brainstorm 2026Oct13 Q9), including when the wall cap ends it.
    """
    run = ResearchRun(writer=writer)
    writer(PLANNING_PROGRESS)
    time_limit_hit = False
    with start_span("deep_research") as span:
        try:
            result = await _invoke(build_graph(run), query)
        except ResearchLimitError:
            time_limit_hit = True
            raise
        finally:
            span.set_attributes(
                {
                    "research.searches_used": run.searches,
                    "research.search_cap": LIMITS.max_searches,
                    "research.sources_read": len(run.sources),
                    "research.search_budget_hit": run.searches >= LIMITS.max_searches,
                    "research.time_limit_hit": time_limit_hit,
                }
            )
    return _checked_deep_answer(result, run)


async def _invoke(graph: Any, query: str) -> dict[str, Any]:
    """Run the agent under the wall-time cap, mapping failures to pipeline errors."""
    deadline = asyncio.timeout(LIMITS.wall_seconds)
    try:
        async with deadline:
            result: dict[str, Any] = await graph.ainvoke(
                {"messages": [HumanMessage(query)], "rubric": DEEP_ANSWER_RUBRIC},
                config=NO_CHECKPOINTER_CONFIG,
            )
            return result
    except TimeoutError as exc:
        if deadline.expired():
            raise ResearchLimitError(
                f"The deep analysis ran past its {LIMITS.wall_seconds:g}-second limit."
            ) from exc
        raise LLMInvocationError("Deep research failed.") from exc
    except PipelineError:
        # A search outage: already the right status.
        raise
    except Exception as exc:  # noqa: BLE001 - one boundary for the whole agent
        raise LLMInvocationError("Deep research failed.") from exc


def _final_deep_answer(result: dict[str, Any]) -> str:
    """Return the last AI message's text; the rubric loop injects human turns."""
    for message in reversed(result.get("messages") or []):
        if isinstance(message, AIMessage):
            return message.text.strip()
    return ""


def _checked_deep_answer(result: dict[str, Any], run: ResearchRun) -> str:
    """Refuse an answer that breaks the expert's rules; never degrade it."""
    if not run.sources:
        raise NoSourcesError(
            "The deep analysis could not read any approved source for this question."
        )
    verdict = run.verdicts[-1] if run.verdicts else None
    if verdict not in SHIPPABLE_VERDICTS:
        raise LLMInvocationError(f"The deep analysis grader ended with {verdict!r}.")
    deep_answer = _final_deep_answer(result)
    if not deep_answer:
        raise LLMInvocationError("The deep analysis returned an empty answer.")
    if not set(MARKDOWN_LINK_URL.findall(deep_answer)) & run.sources.keys():
        raise LLMInvocationError("The deep analysis cited none of the sources it read.")
    if verdict == "max_iterations_reached":
        logger.warning("deep_expert: shipping last draft; grader never satisfied")
    logger.info(
        "deep_expert: %d searches, %d sources read, verdicts=%s, %d answer chars",
        run.searches,
        len(run.sources),
        run.verdicts,
        len(deep_answer),
    )
    return deep_answer
