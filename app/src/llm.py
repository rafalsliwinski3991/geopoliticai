"""OpenAI boundary: one streamed plain-text chain and one structured call."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.constants import TAG_NOSTREAM
from pydantic import BaseModel

from config import DEFAULT_LLM_SETTINGS, LLMSettings
from models import LLMInvocationError

DEFAULT_MAX_RETRIES = 2

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _build_client(settings: LLMSettings) -> ChatOpenAI:
    """Return the configured streaming chat client."""
    return ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        max_completion_tokens=settings.max_output_tokens,
        timeout=settings.timeout_seconds,
        max_retries=DEFAULT_MAX_RETRIES,
        streaming=True,
    )


def _build_structured_client(settings: LLMSettings) -> ChatOpenAI:
    """Return a non-streaming client for one structured-output call.

    `streaming=True` would make even `ainvoke` stream internally, which puts
    the router's own tool-call chunks into any `stream_mode="messages"`
    consumer. This call is never the user's answer, so it never streams.
    """
    return ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        max_completion_tokens=settings.max_output_tokens,
        timeout=settings.timeout_seconds,
        max_retries=DEFAULT_MAX_RETRIES,
        streaming=False,
    )


async def astream_messages(
    system_prompt: str,
    messages: Sequence[BaseMessage],
    *,
    config: RunnableConfig | None = None,
    settings: LLMSettings = DEFAULT_LLM_SETTINGS,
) -> AsyncIterator[str]:
    """Stream plain-text chunks for a system prompt plus a message history."""
    payload = [SystemMessage(system_prompt), *messages]
    try:
        async for chunk in _build_client(settings).astream(payload, config=config):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Model call failed.") from exc


async def astream_text(
    system_prompt: str,
    human_prompt: str,
    *,
    config: RunnableConfig | None = None,
    settings: LLMSettings = DEFAULT_LLM_SETTINGS,
) -> AsyncIterator[str]:
    """Stream plain-text chunks for one system/human prompt pair."""
    async for chunk in astream_messages(
        system_prompt,
        [HumanMessage(human_prompt)],
        config=config,
        settings=settings,
    ):
        yield chunk


async def ainvoke_structured(
    system_prompt: str,
    messages: Sequence[BaseMessage],
    schema: type[SchemaT],
    *,
    config: RunnableConfig | None = None,
    settings: LLMSettings = DEFAULT_LLM_SETTINGS,
) -> SchemaT:
    """Return one schema-validated object from a non-streamed model call.

    Tagged `TAG_NOSTREAM`, so `astream(stream_mode="messages")` never
    registers this call: routing is the app's own reasoning, not the user's
    answer. Verified against langgraph 1.0.1 —
    `langgraph/pregel/_messages.py` skips registration for a tagged run.
    """
    payload = [SystemMessage(system_prompt), *messages]
    chain = (
        _build_structured_client(settings)
        .with_structured_output(schema, method="json_schema", strict=True)
        .with_config(tags=[TAG_NOSTREAM])
    )
    try:
        result = await chain.ainvoke(payload, config=config)
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Structured model call failed.") from exc
    if not isinstance(result, schema):
        raise LLMInvocationError("Structured model call returned no usable object.")
    return result
