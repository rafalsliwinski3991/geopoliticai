"""Graph construction for the deep forecaster (brainstorm 2026Sep30 Q27).

A fixed workflow: every step runs once, in this order, except that `verify`
may send the analysis back to `write_analysis` once, with typed state
between steps. Only `research` is autonomous. The council runs exactly once
because the edges say so, not because a prompt asks.

No node may be named `answer`, `chat` or `write`: `api.stream.ANSWER_NODES` streams
model text from nodes with those names, and this graph runs inside the
orchestrator's `deep_forecaster` node, whose answer reaches the browser once,
as a `notice` (guarded in `tests/unit_tests/test_api.py`).

Built per call by `forecast()`, as the deep expert builds its agent. Nothing
here needs a key; one construction path keeps tests and runtime alike. There
is no checkpointer: `forecast()` also switches the parent's saver off for the
whole tree (`capped_run.NO_CHECKPOINTER_CONFIG`), runs the graph under the
wall cap, and maps its failures to pipeline errors.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.errors import NodeTimeoutError
from langgraph.graph import END, START, StateGraph

from agents.capped_run import invoke_capped
from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.nodes import (
    council_round_1,
    council_round_2,
    draft_claims,
    research,
    tally,
    verify,
    write_analysis,
)
from agents.deep_forecaster.state import ForecastRun, ForecastState
from shared.errors import ResearchLimitError

# (name, node, LangGraph node timeout). Research carries its own soft time
# box; each council round is bounded by its members' timeouts; the two single
# model calls get a hard node timeout, because `services.llm.ainvoke_structured`
# retries and its per-attempt timeout alone would not bound the step.
STEPS: tuple[tuple[str, Any, float | None], ...] = (
    ("research", research, None),
    ("draft_claims", draft_claims, LIMITS.claims_seconds),
    ("council_round_1", council_round_1, None),
    ("council_round_2", council_round_2, None),
    ("tally", tally, None),
    ("write_analysis", write_analysis, LIMITS.write_seconds),
    ("verify", verify, None),
)

logger = logging.getLogger(__name__)


def build_graph() -> Any:
    """Construct and compile the forecaster's fixed workflow."""
    builder = StateGraph(ForecastState, context_schema=ForecastRun)
    previous = START
    for name, node, timeout in STEPS:
        builder.add_node(name, node, timeout=timeout)
        builder.add_edge(previous, name)
        previous = name
    # The one backward edge: `verify` sends a defective analysis back to the
    # writer once (it raises on a second defect, so this cannot loop).
    builder.add_conditional_edges("verify", route_after_verify, ["write_analysis", END])
    return builder.compile(name="deep_forecaster", checkpointer=False)


def route_after_verify(state: ForecastState) -> str:
    """Finish once verify wrote the answer; otherwise rewrite the analysis."""
    return END if "answer" in state else "write_analysis"


async def forecast(query: str, store: Any | None = None) -> str:
    """Forecast on `query` and return the checked answer with its vote list.

    `store` is the parent runtime's store (`Runtime.store`), when the caller
    has one: `research`'s `ask_video` reads its video-notes cache with it
    (review thread, #151); tests may pass None to run cache-less.

    Takes no writer: each step emits its own progress through the graph's
    `runtime.stream_writer`, which reaches the orchestrator's `custom` stream
    under the child namespace (measured, plan §1). The wall cap is a
    dedicated-task cancel (`capped_run.run_under_time_limits`): in smoke gate
    F3, run 1, the frame's `asyncio.timeout` alone did not bound a hung run, and
    the task is cancelled repeatedly, then abandoned, whatever swallows a cancel.
    """
    run = ForecastRun(store=store)
    try:
        result, capped = await invoke_capped(
            build_graph(),
            {"question": query},
            limit_seconds=LIMITS.wall_seconds,
            failure="The forecast failed.",
            context=run,
        )
    except NodeTimeoutError as exc:
        # A step's own node timeout (`STEPS`); not a `TimeoutError`.
        raise ResearchLimitError(
            f"The forecast's step ran past its {exc.timeout:g}-second limit: "
            f"{run.step}."
        ) from exc
    if capped:
        raise ResearchLimitError(
            f"The forecast ran past its {LIMITS.wall_seconds / 60:g}-minute limit "
            f"during this step: {run.step}."
        )
    answer: str = result["answer"]
    logger.info("deep_forecaster: %d answer chars", len(answer))
    return answer
