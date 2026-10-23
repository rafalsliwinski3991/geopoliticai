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
from agents.orchestrator.state import Destination, GeopoliticState
from agents.orchestrator.tools import ALL_TOOLS
from llm import astream_messages, build_chat_model
from models import LLMInvocationError

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
            for call_id, name in unanswered_tool_calls.items():
                sanitized.append(
                    ToolMessage(
                        content=f"Tool execution for {name} was cancelled.",
                        tool_call_id=call_id,
                    )
                )
            unanswered_tool_calls.clear()
            sanitized.append(msg)
        elif isinstance(msg, AIMessage):
            sanitized.append(msg)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = tc.get("id")
                    tc_name = tc.get("name", "tool")
                    if tc_id:
                        unanswered_tool_calls[tc_id] = tc_name
        elif isinstance(msg, ToolMessage):
            if msg.tool_call_id in unanswered_tool_calls:
                unanswered_tool_calls.pop(msg.tool_call_id, None)

            artifact = getattr(msg, "artifact", None)
            if isinstance(artifact, dict) and "text" in artifact:
                sanitized.append(
                    ToolMessage(
                        content=artifact["text"],
                        tool_call_id=msg.tool_call_id,
                        artifact=artifact,
                        name=getattr(msg, "name", None),
                        id=getattr(msg, "id", None),
                    )
                )
            else:
                sanitized.append(msg)
        else:
            sanitized.append(msg)

    for call_id, name in unanswered_tool_calls.items():
        sanitized.append(
            ToolMessage(
                content=f"Tool execution for {name} was cancelled.",
                tool_call_id=call_id,
            )
        )
    unanswered_tool_calls.clear()

    window = sanitized[-HISTORY_WINDOW_MESSAGES:]
    while window and isinstance(window[0], ToolMessage):
        window = window[1:]

    return window


async def supervisor(
    state: GeopoliticState,
    writer: StreamWriter,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Two-phase supervisor node.

    Pass 1 (User turn): Evaluates user intent, picks specialist tool or streams small talk answer.
    Pass 2 (Post-tool): Summarizes next steps into a dynamic footer emitted as a notice chunk.
    """
    last_message = state["messages"][-1] if state.get("messages") else None

    # Pass 2 (Post-tool)
    if isinstance(last_message, ToolMessage):
        prompt = [
            SystemMessage(DYNAMIC_FOOTER_SYSTEM_PROMPT),
            HumanMessage(f"Recent tool result summary: {last_message.content}"),
        ]
        try:
            client = _build_footer_client()
            res = await client.ainvoke(prompt, config=config)
            footer_text = (
                res.content.strip()
                if isinstance(res.content, str) and res.content.strip()
                else STATIC_NEXT_STEPS_MENU
            )
        except Exception:
            logger.exception(
                "Dynamic footer generation failed; falling back to static menu."
            )
            footer_text = STATIC_NEXT_STEPS_MENU

        footer_chunk = f"\n\n---\n{footer_text}"
        writer({"type": "notice", "text": footer_chunk})
        return {"messages": [AIMessage(footer_chunk)]}

    # Pass 1 (User turn)
    sanitized = _sanitize_and_slice_messages(list(state.get("messages", [])))
    payload = [SystemMessage(SUPERVISOR_SYSTEM_PROMPT), *sanitized]
    client = _build_supervisor_client()
    res = await client.ainvoke(payload, config=config)

    if res.tool_calls:
        tc = res.tool_calls[0]
        destination = TOOL_DESTINATION_MAP.get(tc["name"], "other")
        return {
            "messages": [AIMessage(content="", tool_calls=[tc])],
            "destination": destination,
        }

    # Pure conversational small talk / general chat
    chunks: list[str] = []
    async for chunk in astream_messages(
        SUPERVISOR_SYSTEM_PROMPT,
        sanitized,
        config=config,
        settings=SUPERVISOR_LLM_SETTINGS,
    ):
        chunks.append(chunk)

    chat_text = "".join(chunks).strip()
    if not chat_text:
        chat_text = res.content.strip() if isinstance(res.content, str) else ""
    if not chat_text:
        raise LLMInvocationError("Model returned an empty answer.")

    return {"messages": [AIMessage(chat_text)], "destination": "other"}
