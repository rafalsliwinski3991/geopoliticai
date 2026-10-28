"""Two-phase supervisor node for the orchestrator agent."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.constants import TAG_NOSTREAM
from langgraph.types import StreamWriter

from agents.orchestrator.config import (
    FOOTER_LLM_SETTINGS,
    HISTORY_WINDOW_MESSAGES,
    SUPERVISOR_LLM_SETTINGS,
)
from agents.orchestrator.consts.menu import (
    DYNAMIC_FOOTER_SYSTEM_PROMPT,
    STATIC_NEXT_STEPS_MENU,
)
from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT
from agents.orchestrator.state import Destination, OrchestratorState
from agents.orchestrator.tools import ALL_TOOLS
from services.llm import build_chat_model
from shared.config import FOOTER_PREFIX
from shared.errors import LLMInvocationError
from shared.tracing import start_span

logger = logging.getLogger(__name__)

TOOL_DESTINATION_MAP: dict[str, Destination] = {
    "run_expert": "geopolitical",
    "run_deep_expert": "deep",
    "run_deep_forecaster": "forecast",
    "run_reporter": "report",
}


def _build_supervisor_client() -> Runnable[Any, Any]:
    return (
        build_chat_model(SUPERVISOR_LLM_SETTINGS)
        .bind_tools(ALL_TOOLS, parallel_tool_calls=False)
        .with_config(tags=[TAG_NOSTREAM])
    )


def _build_footer_client() -> Runnable[Any, Any]:
    return build_chat_model(FOOTER_LLM_SETTINGS).with_config(tags=[TAG_NOSTREAM])


def _cancel_unanswered_tool_calls(unanswered: dict[str, str]) -> list[ToolMessage]:
    """Close each tool call the thread never answered, and forget them."""
    cancellations = [
        ToolMessage(
            content=f"Tool execution for {name} was cancelled.",
            tool_call_id=call_id,
        )
        for call_id, name in unanswered.items()
    ]
    unanswered.clear()
    return cancellations


def _sanitize_and_slice_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Sanitize conversation history and apply sliding window with orphan guard.

    - Replaces ToolMessage.content with msg.artifact["text"] if present.
    - Tracks unanswered tool calls and injects synthetic cancellations if interrupted.
    - Slices to HISTORY_WINDOW_MESSAGES.
    - Drops leading ToolMessages in the sliced window to avoid API protocol errors.
    """
    sanitized: list[AnyMessage] = []
    unanswered_tool_calls: dict[str, str] = {}

    for msg in messages:
        if isinstance(msg, HumanMessage):
            sanitized.extend(_cancel_unanswered_tool_calls(unanswered_tool_calls))
            sanitized.append(msg)
        elif isinstance(msg, AIMessage):
            sanitized.append(msg)
            for tc in msg.tool_calls:
                tc_id = tc.get("id")
                if tc_id:
                    unanswered_tool_calls[tc_id] = tc.get("name", "tool")
        elif isinstance(msg, ToolMessage):
            unanswered_tool_calls.pop(msg.tool_call_id, None)
            artifact = msg.artifact
            if isinstance(artifact, dict) and "text" in artifact:
                sanitized.append(msg.model_copy(update={"content": artifact["text"]}))
            else:
                sanitized.append(msg)
        else:
            sanitized.append(msg)

    sanitized.extend(_cancel_unanswered_tool_calls(unanswered_tool_calls))

    window = sanitized[-HISTORY_WINDOW_MESSAGES:]
    while window and isinstance(window[0], ToolMessage):
        window = window[1:]

    return window


async def _invoke(
    client: Runnable[Any, Any],
    payload: list[AnyMessage],
    config: Optional[RunnableConfig],
) -> AIMessage:
    """Call the model once; a provider failure is an `LLMInvocationError` (502)."""
    try:
        res: AIMessage = await client.ainvoke(payload, config=config)
    except Exception as exc:  # noqa: BLE001 - single provider boundary
        raise LLMInvocationError("Model call failed.") from exc
    return res


async def supervisor(
    state: OrchestratorState,
    writer: StreamWriter,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Two-phase supervisor node.

    Pass 1 (User turn): Evaluates user intent, picks specialist tool or answers small talk.
    Pass 2 (Post-tool): Summarizes next steps into a dynamic footer emitted as a notice chunk.
    """
    last_message = state["messages"][-1] if state.get("messages") else None

    with start_span("supervisor") as span:
        # Pass 2 (Post-tool)
        if isinstance(last_message, ToolMessage):
            span.set_attribute("supervisor.pass", "footer")
            prompt: list[AnyMessage] = [
                SystemMessage(DYNAMIC_FOOTER_SYSTEM_PROMPT),
                HumanMessage(f"Recent tool result summary: {last_message.content}"),
            ]
            footer_text = ""
            try:
                res = await _invoke(_build_footer_client(), prompt, config)
                footer_text = res.text.strip()
            except LLMInvocationError:
                logger.exception("Dynamic footer generation failed.")
            span.set_attribute("supervisor.footer_fallback", not footer_text)

            footer_chunk = f"{FOOTER_PREFIX}{footer_text or STATIC_NEXT_STEPS_MENU}"
            writer({"type": "notice", "text": footer_chunk})
            return {"messages": [AIMessage(footer_chunk)]}

        # Pass 1 (User turn)
        span.set_attribute("supervisor.pass", "route")
        sanitized = _sanitize_and_slice_messages(list(state.get("messages", [])))
        span.set_attribute("supervisor.history_messages", len(sanitized))
        payload = [SystemMessage(SUPERVISOR_SYSTEM_PROMPT), *sanitized]
        res = await _invoke(_build_supervisor_client(), payload, config)

        if res.invalid_tool_calls:
            raise LLMInvocationError("Model returned a tool call it could not parse.")

        if res.tool_calls:
            tc = res.tool_calls[0]
            if not any(str(value).strip() for value in tc["args"].values()):
                raise LLMInvocationError("Model returned a tool call with no query.")
            try:
                destination = TOOL_DESTINATION_MAP[tc["name"]]
            except KeyError as exc:
                raise LLMInvocationError(
                    f"Model called an unknown tool: {tc['name']}."
                ) from exc
            span.set_attribute("supervisor.tool", tc["name"])
            span.set_attribute("supervisor.destination", destination)
            return {
                "messages": [AIMessage(content="", tool_calls=[tc])],
                "destination": destination,
            }

        # Small talk or general chat: the first call already holds the answer.
        chat_text = res.text.strip()
        if not chat_text:
            raise LLMInvocationError("Model returned an empty answer.")
        span.set_attribute("supervisor.destination", "other")
        return {"messages": [AIMessage(chat_text)], "destination": "other"}
