"""Routing and query rewriting (graph node 1)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.orchestrator.config import CLASSIFY_LLM_SETTINGS, HISTORY_WINDOW_MESSAGES
from agents.orchestrator.prompts import CLASSIFY_SYSTEM_PROMPT
from agents.orchestrator.state import OrchestratorState, RouteDecision
from llm import ainvoke_structured
from models import LLMInvocationError

logger = logging.getLogger(__name__)


async def classify(
    state: OrchestratorState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Pick the branch and rewrite the turn, in one structured model call."""
    history = list(state["messages"])[-HISTORY_WINDOW_MESSAGES:]
    decision = await ainvoke_structured(
        CLASSIFY_SYSTEM_PROMPT,
        history,
        RouteDecision,
        config=config,
        settings=CLASSIFY_LLM_SETTINGS,
    )
    standalone_query = " ".join(decision.standalone_query.split())
    if not standalone_query:
        # An empty rewrite would reach `search_and_fetch` as an empty Brave
        # query and come back as a confusing NoSourcesError. Fail here, where
        # the cause is still visible.
        raise LLMInvocationError("Classifier returned an empty standalone query.")
    logger.info(
        "classify: destination=%s, %d chars in",
        decision.destination,
        len(standalone_query),
    )
    return {
        "destination": decision.destination,
        "standalone_query": standalone_query,
    }
