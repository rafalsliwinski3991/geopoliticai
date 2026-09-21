"""Answer composition (graph node 2)."""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from agents.expert.config import ANSWER_LLM_SETTINGS
from agents.expert.prompts import ANSWER_SYSTEM_PROMPT
from agents.expert.state import PipelineState
from llm import astream_text
from models import LLMInvocationError, NoSourcesError, Source

logger = logging.getLogger(__name__)


def _sources_block(sources: list[Source]) -> str:
    """Render fetched sources for the prompt."""
    return "\n\n".join(
        f"--- SOURCE ---\nTitle: {source.title}\nURL: {source.url}\n\n{source.text}"
        for source in sources
    )


async def answer(
    state: PipelineState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Write the finished answer from fetched sources in one streamed call."""
    sources = state["sources"]
    if not sources:
        raise NoSourcesError("Answer node reached with no sources.")
    human_prompt = (
        f"Question: {state['query']}\n\nSource documents:\n\n{_sources_block(sources)}"
    )
    logger.info("answer: %d sources, prompt %d chars", len(sources), len(human_prompt))
    chunks: list[str] = []
    async for chunk in astream_text(
        ANSWER_SYSTEM_PROMPT, human_prompt, config=config, settings=ANSWER_LLM_SETTINGS
    ):
        chunks.append(chunk)
    text = "".join(chunks).strip()
    if not text:
        raise LLMInvocationError("Model returned an empty answer.")
    return {"answer": text}
