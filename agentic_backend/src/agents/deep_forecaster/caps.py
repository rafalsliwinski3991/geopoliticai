"""Wall caps that survive a hung agent run (smoke gate F3, run 1, 2026-10-01).

langgraph 1.2.12's pregel runner absorbs a `CancelledError` delivered while
its agent loop is running (measured: `asyncio.timeout` in the calling frame
does not end a deepagents run whose model call hangs; the run limps on until
its own client timeouts, spending searches and paid calls the whole way).
The cap therefore runs the work in a dedicated task and, on expiry, cancels
that task directly; a task that swallows cancels is cancelled repeatedly and,
if it still outlives the grace, abandoned with a warning — it dies at its own
client timeouts, and the caller's cap error is not delayed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# How long one cancel has to take effect, and how many are retried before the
# capped task is abandoned (a task that swallows cancels is bounded only by
# its own client timeouts).
GRACE_SECONDS = 0.25
REPEATS = 3


async def run_under_cap(coro: Any, cap_seconds: float) -> tuple[Any, bool]:
    """Return `(result, capped)`: the coroutine's result, or `capped=True`.

    A run the cap ends has no result: `capped` is True and `result` is None.
    The caller's own cancellation cancels the inner task too (no orphan).
    """
    task: asyncio.Task[Any] = asyncio.ensure_future(coro)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + cap_seconds
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
                "A capped run outlived %d cancels; abandoning it to its own "
                "client timeouts.",
                REPEATS,
            )
        return None, True
    except BaseException:
        # The caller was cancelled (or failed): the inner run must not outlive it.
        if not task.done():
            task.cancel()
        raise
