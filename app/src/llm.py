"""OpenAI boundary: one streamed plain-text chain."""

from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from config import get_model, get_openai_max_output_tokens, get_openai_timeout_seconds

DEFAULT_MAX_RETRIES = 2


class LLMInvocationError(RuntimeError):
    """Raised when the model call fails or returns nothing usable."""


def _build_client() -> ChatOpenAI:
    """Return the configured chat client used by the answer node."""
    return ChatOpenAI(
        model=get_model(),
        temperature=0.0,
        max_completion_tokens=get_openai_max_output_tokens(),
        timeout=get_openai_timeout_seconds(),
        max_retries=DEFAULT_MAX_RETRIES,
        streaming=True,
    )


async def astream_text(
    system_prompt: str, human_prompt: str, *, config: RunnableConfig | None = None
) -> AsyncIterator[str]:
    """Stream plain-text chunks for one system/human prompt pair."""
    messages = [SystemMessage(system_prompt), HumanMessage(human_prompt)]
    try:
        async for chunk in _build_client().astream(messages, config=config):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Model call failed.") from exc
