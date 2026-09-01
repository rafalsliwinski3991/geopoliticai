"""Delegation to the expert agent (graph node 2b)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage

from agents.expert import build_initial_pipeline_state
from agents.expert import graph as expert_graph
from agents.orchestrator.state import OrchestratorState

logger = logging.getLogger(__name__)


async def expert(state: OrchestratorState) -> dict[str, Any]:
    """Run the compiled expert graph on the classifier's standalone query.

    The expert is *invoked here*, not handed to `add_node` directly. Its state
    is `{query, sources, answer}` and shares no key with this graph's, and
    LangGraph 1.0.1 does not reject that: it hands the child an input with no
    `query` and discards whatever the child returns, with no error. Invoking
    it keeps the boundary exactly as specified — one plain string in, one
    finished answer out, no message history inside the expert — and because
    the call happens inside a node, its answer tokens still reach
    `astream(..., subgraphs=True)` under the `expert:<task id>` namespace.

    No `config` is passed: LangGraph propagates the parent run through
    contextvars, which is what produces that namespace. Passing the parent
    config explicitly would do the same thing less obviously.
    """
    result = await expert_graph.ainvoke(
        build_initial_pipeline_state(state["standalone_query"])
    )
    answer: str = result["answer"]
    logger.info("expert: %d answer chars", len(answer))
    return {"messages": [AIMessage(answer)]}
