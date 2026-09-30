"""Delegation to the deep expert agent (graph node 2d)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from agents.deep_expert import research
from agents.orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)


async def deep_expert(state: OrchestratorState, writer: StreamWriter) -> dict[str, Any]:
    """Research the classifier's standalone query in depth.

    Called here, not handed to `add_node`, for the expert's reason: the deep
    agent's state shares only `messages` with this graph, and the boundary is
    one string in, one answer out.

    The answer goes out once as a `notice`. The agent's own model calls run in
    nodes named `model`/`tools`, which are not in `api.ANSWER_NODES`, so drafts,
    tool calls and grader chatter never stream. The returned `AIMessage` is
    tagged `deep_expert`, also not in `ANSWER_NODES`, so it is not sent twice.
    A `notice`, unlike `progress`, passes through `MAX_ANSWER_CHARS`.

    `writer` must be annotated exactly `StreamWriter` (see `classify`).
    """
    deep_answer = await research(state["standalone_query"], writer)
    writer({"type": "notice", "text": deep_answer})
    logger.info("deep_expert: %d answer chars", len(deep_answer))
    return {"messages": [AIMessage(deep_answer)]}
