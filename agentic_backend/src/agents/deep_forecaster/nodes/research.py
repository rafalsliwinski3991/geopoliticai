"""The research step (graph node 1): the only autonomous step (brainstorm Q27).

A deepagents lead picks the forecasters (Q19) and sends one scout per
forecaster at once (Q18). The lead gets no research tools, so it can only
delegate. Of deepagents' built-in file tools, the lead and the scout keep only
`read_file`, which deepagents requires (`middleware/filesystem.py:1777`) and
which reads a tool result deepagents saved to a file; `ls`, `write_file`,
`edit_file`, `glob`, `grep` and `delete` are removed by configuration, not by
prompt (v2 review). `execute` is never offered with the default in-state
backend. The node returns what the scouts' tools recorded, never the lead's
text: the sources are the step's whole output.
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.filesystem import FilesystemMiddleware, FsToolName
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from agents.deep_expert.graph import NO_CHECKPOINTER_CONFIG
from agents.deep_forecaster.config import LIMITS, RESEARCH_LLM_SETTINGS
from agents.deep_forecaster.consts.forecasters import FORECASTERS
from agents.deep_forecaster.consts.progress import RESEARCH_LABEL
from agents.deep_forecaster.prompts import (
    LEAD_SYSTEM_PROMPT,
    SCOUT_DESCRIPTION,
    SCOUT_PROMPT,
)
from agents.deep_forecaster.state import (
    ForecastRun,
    ForecastState,
    ResearchOutcome,
    ResearchRun,
)
from agents.deep_forecaster.time_limits import run_under_time_limits
from agents.deep_forecaster.tools import build_tools
from llm import build_chat_model
from models import (
    LLMInvocationError,
    NoSourcesError,
    PipelineError,
    SearchUnavailableError,
)
from tracing import start_span

# deepagents' reserved name: a spec under it replaces the auto-added default
# subagent (`deepagents/graph.py:798`), so the scout is the lead's only one.
SCOUT_SUBAGENT_NAME = "general-purpose"
# The only built-in file tool kept; deepagents refuses a filesystem without it.
# Typed, because `FilesystemMiddleware(tools=...)` takes `list[FsToolName]`
# and mypy --strict refuses a `list[str]` (correctness review).
KEPT_FILE_TOOLS: list[FsToolName] = ["read_file"]
logger = logging.getLogger(__name__)


def _forecaster_lines() -> str:
    """Return the lead's roster: one `- id: name, focus (language)` line each."""
    return "\n".join(
        f"- {f.id}: {f.name}, {f.focus} (publishes in {f.language})"
        for f in FORECASTERS
    )


def build_research_agent(run: ResearchRun) -> Any:
    """Construct the lead and its scout for one forecast; built per call.

    Per call because the tools close over this forecast's `ResearchRun`, and
    `ChatOpenAI` cannot be built without a key. `checkpointer=False` covers the
    lead's own loop; the whole tree runs under `NO_CHECKPOINTER_CONFIG`.
    """
    model = build_chat_model(RESEARCH_LLM_SETTINGS)
    # Annotated: the subagent spec's `middleware` is a list of
    # `AgentMiddleware`, which mypy --strict will not infer from a
    # `FilesystemMiddleware` list literal (correctness review, measured).
    scout_middleware: list[AgentMiddleware[Any, Any, Any]] = [
        FilesystemMiddleware(tools=KEPT_FILE_TOOLS)
    ]
    return create_deep_agent(
        model,
        [],
        system_prompt=LEAD_SYSTEM_PROMPT.format(
            forecasters=_forecaster_lines(),
            max_searches=LIMITS.max_searches,
            max_sources=LIMITS.max_sources,
            max_videos=LIMITS.max_videos,
        ),
        # A filesystem middleware of our own replaces the default one, per
        # agent, so the deep expert (same model) keeps its tools (framework
        # review, verified on 0.7.19).
        middleware=[FilesystemMiddleware(tools=KEPT_FILE_TOOLS)],
        subagents=[
            {
                "name": SCOUT_SUBAGENT_NAME,
                "description": SCOUT_DESCRIPTION,
                "system_prompt": SCOUT_PROMPT,
                "tools": build_tools(run),
                "model": model,
                "middleware": scout_middleware,
            }
        ],
        checkpointer=False,
        name="forecast_research",
    )


async def research(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Collect the forecasters' writing on the question; return what was read."""
    runtime.context.enter(RESEARCH_LABEL, runtime.stream_writer)
    run = ResearchRun(writer=runtime.stream_writer, store=runtime.store)
    timed_out = False
    with start_span("forecast_research") as span:
        try:
            timed_out = await _run_agent(build_research_agent(run), state["question"])
        finally:
            span.set_attributes(
                {
                    "research.searches_used": run.searches,
                    "research.search_cap": LIMITS.max_searches,
                    "research.failed_searches": run.failed_searches,
                    "research.sources_read": len(run.sources),
                    "research.source_cap": LIMITS.max_sources,
                    "research.videos_used": run.videos,
                    "research.search_budget_hit": run.searches >= LIMITS.max_searches,
                    "research.source_budget_hit": len(run.sources)
                    >= LIMITS.max_sources,
                    "research.time_limit_hit": timed_out,
                }
            )
    if not run.sources:
        if run.searches and run.failed_searches == run.searches:
            # Every Brave request failed: an outage, as the deep expert reports it.
            raise SearchUnavailableError("Every search for this forecast failed.")
        raise NoSourcesError(
            "The forecast found no readable writing by the forecasters on this question."
        )
    logger.info(
        "forecast research: %d searches (%d failed), %d sources, %d videos%s",
        run.searches,
        run.failed_searches,
        len(run.sources),
        run.videos,
        "; time box reached" if timed_out else "",
    )
    return {
        "sources": list(run.sources.values()),
        "research": ResearchOutcome(
            searches=run.searches,
            failed_searches=run.failed_searches,
            timed_out=timed_out,
        ),
    }


async def _run_agent(agent: Any, question: str) -> bool:
    """Run the lead inside its time box; return whether the box ended it.

    The box ending is not an error (user decision 2026-09-30): the forecast
    continues on what was read, and the answer's evidence line says so. The
    box is a dedicated-task cancel (`time_limits.run_under_time_limits`): the pregel runner
    absorbs a `CancelledError` raised inside its own loop, so the frame's
    `asyncio.timeout` alone does not end a hung agent (smoke gate F3, run 1).
    """
    try:
        _, timed_out = await run_under_time_limits(
            agent.ainvoke(
                {"messages": [HumanMessage(question)]}, config=NO_CHECKPOINTER_CONFIG
            ),
            LIMITS.research_seconds,
        )
    except TimeoutError as exc:
        raise LLMInvocationError("The forecast's research failed.") from exc
    except PipelineError:
        # Already the right status (no tool raises one today; kept as the deep
        # expert's boundary does).
        raise
    except Exception as exc:  # noqa: BLE001 - one boundary for the whole agent
        raise LLMInvocationError("The forecast's research failed.") from exc
    return timed_out
