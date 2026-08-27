"""OpenAI boundary: one streamed plain-text chain."""

from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from config import DEFAULT_LLM_SETTINGS, LLMSettings

DEFAULT_MAX_RETRIES = 2


class LLMInvocationError(RuntimeError):
    """Raised when the model call fails or returns nothing usable."""


def _build_client(settings: LLMSettings) -> ChatOpenAI:
    """Return the configured chat client used by the answer node."""
    return ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        max_completion_tokens=settings.max_output_tokens,
        timeout=settings.timeout_seconds,
        max_retries=DEFAULT_MAX_RETRIES,
        streaming=True,
    )


async def astream_text(
    system_prompt: str,
    human_prompt: str,
    *,
    config: RunnableConfig | None = None,
    settings: LLMSettings = DEFAULT_LLM_SETTINGS,
) -> AsyncIterator[str]:
    """Stream plain-text chunks for one system/human prompt pair."""
    messages = [SystemMessage(system_prompt), HumanMessage(human_prompt)]
    try:
        async for chunk in _build_client(settings).astream(messages, config=config):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Model call failed.") from exc
