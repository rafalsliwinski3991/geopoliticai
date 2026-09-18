"""Report composition (graph node 3)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from agents.reporter.config import MAX_REPORT_CHARS, REPORT_LLM_SETTINGS
from agents.reporter.consts.progress import REPORT_PROGRESS
from agents.reporter.prompts import REPORT_SYSTEM_PROMPT
from agents.reporter.state import ReporterState
from llm import astream_text
from models import LLMInvocationError

logger = logging.getLogger(__name__)


async def write(
    state: ReporterState,
    writer: StreamWriter,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Write the approved report in one streamed call.

    This node's name is load-bearing twice over: `api.ANSWER_NODES` forwards
    streamed `AIMessage` chunks tagged `langgraph_node == "write"`, and
    `_astream_answer` uses the same tag to emit the `("kind", "report")` event
    that puts a Download .md button on the answer. Renaming it would silently
    stop the report reaching the browser. Measured: after a resume, these chunks
    do arrive at the parent tagged `"write"`.

    The progress event is emitted before the call and, measured, reaches the
    parent's `astream` ahead of the first token chunk — so the browser shows
    "Writing the report..." and then the report, in that order.
    """
    writer(REPORT_PROGRESS)
    outline_block = "\n".join(f"{i}. {s}" for i, s in enumerate(state["outline"], 1))
    human_prompt = (
        f"Approved outline:\n\n{outline_block}\n\n"
        f"Conversation transcript:\n\n{state['transcript']}"
    )
    logger.info(
        "write: %d sections, prompt %d chars", len(state["outline"]), len(human_prompt)
    )
    chunks: list[str] = []
    async for chunk in astream_text(
        REPORT_SYSTEM_PROMPT, human_prompt, config=config, settings=REPORT_LLM_SETTINGS
    ):
        chunks.append(chunk)
    text = "".join(chunks).strip()
    if not text:
        raise LLMInvocationError("Model returned an empty report.")
    if len(text) > MAX_REPORT_CHARS:
        # The stream is drained fully above before this trim, so the model call
        # completes normally; only what is *stored* is bounded. See
        # MAX_REPORT_CHARS for why storing more helps nobody. Note this bounds
        # the checkpoint only — the browser was already capped independently by
        # `api.MAX_ANSWER_CHARS` as the chunks streamed past.
        logger.info("write: report clipped from %d chars", len(text))
        text = text[:MAX_REPORT_CHARS]
    return {"report": text}
