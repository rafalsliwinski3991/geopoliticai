"""Delegation to the deep forecaster (graph node 2e)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from agents.deep_forecaster import forecast
from agents.orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)


async def deep_forecaster(
    state: OrchestratorState, runtime: Runtime[Any]
) -> dict[str, Any]:
    """Forecast on the classifier's standalone query.

    Called here, not handed to `add_node`, for the expert's reason: the
    forecaster's state shares no key with this graph, and the boundary is one
    string in, one answer out. Its steps emit their own progress.

    The answer goes out once as a `notice`. The forecaster's model calls run
    in nodes none of which is in `api.ANSWER_NODES` (its own steps, and
    deepagents' `model`/`tools`); its structured and council calls are also
    tagged `TAG_NOSTREAM`. The returned `AIMessage` is tagged
    `deep_forecaster`, also not in `ANSWER_NODES`, so it is not sent twice.

    The notice is written through `runtime.stream_writer`: a `writer`
    parameter cannot combine with `runtime` in `add_node`'s typing (review
    thread, #151).
    """
    # The parent's store reaches the child's video-notes cache through the
    # runtime injection (thread, #151): without it `ask_video` would always
    # bypass the 30-day cache and every forecast would call Gemini.
    answer = await forecast(state["standalone_query"], runtime.store)
    runtime.stream_writer({"type": "notice", "text": answer})
    logger.info("deep_forecaster: %d answer chars", len(answer))
    return {"messages": [AIMessage(answer)]}
