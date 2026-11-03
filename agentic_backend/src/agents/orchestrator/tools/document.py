"""Specialist tool: answer from the document attached to the thread."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AnyMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command

from agents.document import ask_document
from agents.document.config import RETRIEVAL
from agents.orchestrator.consts.progress import DOCUMENT_PROGRESS
from agents.orchestrator.state import OrchestratorContext, OrchestratorState
from shared.errors import NoDocumentError


def _message_text(message: AnyMessage) -> str:
    """Return a message's text; a tool message's answer lives in its artifact."""
    artifact = getattr(message, "artifact", None)
    if (
        isinstance(message, ToolMessage)
        and isinstance(artifact, dict)
        and "text" in artifact
    ):
        return str(artifact["text"])
    return str(message.text)


def _recent_texts(messages: list[AnyMessage]) -> list[str]:
    """Return the last few messages as `role: text` lines, for the rewrite step."""
    lines = [
        f"{message.type}: {text}"
        for message in messages
        if message.type in ("human", "ai", "tool") and (text := _message_text(message))
    ]
    return lines[-RETRIEVAL.history_messages :]


@tool
async def run_document(
    query: str,
    runtime: ToolRuntime[OrchestratorContext, OrchestratorState],
) -> Command[Any]:
    """Answer a question from the document attached to this conversation.

    Pass `query` as the user's latest message, unchanged.
    """
    search = runtime.context.search_document if runtime.context else None
    if search is None:
        raise NoDocumentError("This conversation has no document.")
    runtime.stream_writer(DOCUMENT_PROGRESS)
    history = _recent_texts(list(runtime.state.get("messages", [])))
    result = await ask_document(query, history, search)
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        f"Answered '{query}' from {len(result['chunks'])} excerpts "
                        "of the attached document."
                    ),
                    tool_call_id=runtime.tool_call_id or "",
                    artifact={"text": result["answer"]},
                )
            ]
        }
    )
