"""Routing and query rewriting (graph node 1)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from agents.orchestrator.config import CLASSIFY_LLM_SETTINGS, HISTORY_WINDOW_MESSAGES
from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.orchestrator.prompts import CLASSIFY_SYSTEM_PROMPT
from agents.orchestrator.state import OrchestratorState, RouteDecision
from llm import ainvoke_structured
from models import LLMInvocationError

logger = logging.getLogger(__name__)


async def classify(
    state: OrchestratorState,
    writer: StreamWriter,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Pick the branch and rewrite the turn, in one structured model call.

    The node announces its own routing decision. Before this change `api.py`
    reconstructed it by reading `data.get("classify")["destination"]` out of
    `stream_mode="updates"` and matching the string against a label table it
    kept itself — the delivery layer knowing this node's name, this node's
    state key, and this node's vocabulary. Saying it here costs one line and
    deletes all three couplings.

    Only the expert branch gets a frame from here. `chat` answers immediately,
    so its "Thinking..." is enough; `report` is announced by the reporter's own
    `outline` node, which also covers the revision rounds this node never sees
    because `classify` does not re-run on a resume.

    `writer` must be annotated exactly `StreamWriter`. Any other spelling —
    `StreamWriter | None`, or a qualified `lg_types.StreamWriter` — is silently
    not injected under `from __future__ import annotations`, and this node then
    emits nothing forever with no error. See §4.0. `config` has the same
    constraint and a narrower allow-list: only `RunnableConfig` and
    `Optional[RunnableConfig]`, never the PEP 604 `RunnableConfig | None`.
    """
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
    if decision.destination == "geopolitical":
        writer(SEARCH_PROGRESS)
    logger.info(
        "classify: destination=%s, %d chars in",
        decision.destination,
        len(standalone_query),
    )
    return {
        "destination": decision.destination,
        "standalone_query": standalone_query,
    }
