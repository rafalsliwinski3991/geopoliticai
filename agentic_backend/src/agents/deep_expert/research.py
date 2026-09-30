"""Run one deep research turn and hold its result to the agent's hard rules."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import CONFIG_KEY_CHECKPOINTER
from langgraph.types import StreamWriter

from agents.deep_expert.config import LIMITS
from agents.deep_expert.consts.progress import PLANNING_PROGRESS
from agents.deep_expert.graph import build_graph
from agents.deep_expert.prompts import DEEP_ANSWER_RUBRIC
from agents.deep_expert.state import ResearchRun
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    ResearchLimitError,
)

# Same pattern as `evals/helpers/judge.py::MARKDOWN_LINK_URL`; src never imports evals.
MARKDOWN_LINK_URL = re.compile(r"\]\((https?://[^)\s]+)\)")
# `max_iterations_reached` ships the last draft (brainstorm Q7A); `failed` and
# `grader_error` are hard errors; no verdict at all means the grader never ran.
SHIPPABLE_VERDICTS = frozenset({"satisfied", "max_iterations_reached"})
# Invoked inside the orchestrator's node, every nested run would inherit its
# Postgres saver: `checkpointer=False` covers only the agent's own loop, while
# its tasks still pass the parent saver down (langgraph 1.2.12
# `pregel/_algo.py:737-740`) to the `task` subagent and the rubric grader. A
# None under this key reaches the whole tree and disables all of it.
# `langgraph.constants` keeps the name public through 1.x; the pin is <1.3.
NO_CHECKPOINTER_CONFIG: RunnableConfig = {
    "configurable": {CONFIG_KEY_CHECKPOINTER: None}
}
logger = logging.getLogger(__name__)


async def research(query: str, writer: StreamWriter) -> str:
    """Research `query` in depth and return the finished, checked answer."""
    run = ResearchRun(writer=writer)
    writer(PLANNING_PROGRESS)
    result = await _invoke(build_graph(run), query)
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
