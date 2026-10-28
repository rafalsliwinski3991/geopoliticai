"""Running a graph with no checkpointer under a wall cap, with one error boundary.

The deep expert, the forecast, and the forecast's research step all run a graph
this way (brainstorm 2026Oct22 Q4). `run_under_time_limits` moved here from
`deep_forecaster/time_limits.py` unchanged: in smoke gate F3, run 1
(2026-10-01), an in-frame `asyncio.timeout` did not end a deepagents run whose
model call hung, so the limit runs the work in a dedicated task and cancels that
task directly, repeatedly, then abandons it.

That `run_under_time_limits` function is named per user decision 2026-10-08
(review thread #144), which named its module `time_limits`; the module is now
`capped_run`, and the function keeps its name.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.constants import CONFIG_KEY_CHECKPOINTER
from langgraph.errors import NodeTimeoutError

from shared.errors import LLMInvocationError, PipelineError

logger = logging.getLogger(__name__)

# How long one cancel has to take effect, and how many are retried before the
# capped task is abandoned (a task that swallows cancels is bounded only by
# its own client timeouts).
GRACE_SECONDS = 0.25
REPEATS = 3
# Invoked inside the orchestrator's node, every nested run would inherit its
# Postgres saver: `checkpointer=False` covers only the agent's own loop, while
# its tasks still pass the parent saver down (langgraph 1.2.12
# `pregel/_algo.py:737-740`) to the `task` subagent and the rubric grader. A
# None under this key reaches the whole tree and disables all of it.
# `langgraph.constants` keeps the name public through 1.x; the pin is <1.3.
NO_CHECKPOINTER_CONFIG: RunnableConfig = {
    "configurable": {CONFIG_KEY_CHECKPOINTER: None}
}


async def run_under_time_limits(coro: Any, limit_seconds: float) -> tuple[Any, bool]:
    """Return `(result, timed_out)`: the coroutine's result, or `timed_out=True`.

    A run the limit ends has no result: `timed_out` is True and `result` is
    None. The caller's own cancellation cancels the inner task too (no
    orphan), with the same bounded repeat-cancel grace (review thread, #144).
    """
    task: asyncio.Task[Any] = asyncio.ensure_future(coro)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit_seconds
    try:
        while True:
            left = deadline - loop.time()
            if left <= 0:
                break
            done, _ = await asyncio.wait({task}, timeout=left)
            if done:
                return task.result(), False
            # The cap fired: cancel the task directly (a `CancelledError`
            # raised inside the agent stack itself can be absorbed).
            task.cancel()
            await asyncio.wait({task}, timeout=GRACE_SECONDS)
        for _ in range(REPEATS):
            if task.done():
                break
            task.cancel()
            await asyncio.wait({task}, timeout=GRACE_SECONDS)
        if not task.done():
            logger.warning(
                "A time-limit run outlived %d cancels; abandoning it to its own "
                "client timeouts.",
                REPEATS,
            )
        else:
            # The task finished during the grace loop: its outcome is read so
            # an exception there is not silently misreported as a time limit
            # (review thread, #144).
            if not task.cancelled():
                error = task.exception()
                if error is not None:
                    logger.warning(
                        "A task cancelled at the time limit failed: %s: %s",
                        type(error).__name__,
                        error,
                    )
        return None, True
    except BaseException:
        # The caller was cancelled (or failed): the inner run must not outlive
        # it (review thread, #144). The agent stack can absorb one cancel, so
        # the same bounded repeat-cancel-with-grace loop runs here, shielded
        # because the caller's cancellation may re-deliver while we wait.
        for _ in range(REPEATS):
            if task.done():
                break
            task.cancel()
            try:
                await asyncio.shield(asyncio.wait({task}, timeout=GRACE_SECONDS))
            except asyncio.CancelledError:
                pass
        if not task.done():
            logger.warning(
                "A cancelled caller's inner run outlived %d cancels; abandoning "
                "it to its own client timeouts.",
                REPEATS,
            )
        raise


async def invoke_capped(
    graph: Any,
    graph_input: Any,
    *,
    limit_seconds: float,
    failure: str,
    context: Any = None,
) -> tuple[Any, bool]:
    """Run `graph` once with no checkpointer under `limit_seconds`; return `(result, capped)`.

    A capped run has no result (`None, True`): the caller raises its own limit
    error, worded for its step. A `PipelineError` is already the right status
    and passes through, as does a node's own `NodeTimeoutError`, which the
    forecast words with its step. Anything else becomes
    `LLMInvocationError(failure)`. `context` is passed only when given: the
    deep agents take none.
    """
    extra = {} if context is None else {"context": context}
    try:
        return await run_under_time_limits(
            graph.ainvoke(graph_input, config=NO_CHECKPOINTER_CONFIG, **extra),
            limit_seconds,
        )
    except (PipelineError, NodeTimeoutError):
        raise
    except Exception as exc:  # noqa: BLE001 - one boundary for every capped run
        raise LLMInvocationError(failure) from exc
