"""General-assistant answer for non-geopolitical turns (graph node 2a)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from agents.orchestrator.config import CHAT_LLM_SETTINGS, HISTORY_WINDOW_MESSAGES
from agents.orchestrator.prompts import CHAT_SYSTEM_PROMPT
from agents.orchestrator.state import OrchestratorState
from llm import astream_messages
from models import LLMInvocationError

logger = logging.getLogger(__name__)


async def chat(
    state: OrchestratorState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Answer from the model's own knowledge, with no sources and no citations."""
    history = list(state["messages"])[-HISTORY_WINDOW_MESSAGES:]
    chunks: list[str] = []
    async for chunk in astream_messages(
        CHAT_SYSTEM_PROMPT, history, config=config, settings=CHAT_LLM_SETTINGS
    ):
        chunks.append(chunk)
    text = "".join(chunks).strip()
    if not text:
        raise LLMInvocationError("Model returned an empty answer.")
    logger.info("chat: %d answer chars", len(text))
    return {"messages": [AIMessage(text)]}
