"""Outline proposal and revision (graph node 1)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from agents.reporter.config import MAX_REVISION_ROUNDS, OUTLINE_LLM_SETTINGS
from agents.reporter.consts.messages import NO_MATERIAL_NOTICE, REVISION_CAP_NOTICE
from agents.reporter.consts.progress import OUTLINE_PROGRESS
from agents.reporter.prompts import OUTLINE_SYSTEM_PROMPT
from agents.reporter.state import OutlineDraft, ReporterState
from llm import ainvoke_structured

logger = logging.getLogger(__name__)


def _human_prompt(state: ReporterState) -> str:
    """Render the transcript, the current outline, and any revision request."""
    parts = [f"Conversation transcript:\n\n{state['transcript']}"]
    if state["outline"]:
        current = "\n".join(f"{i}. {s}" for i, s in enumerate(state["outline"], 1))
        parts.append(f"Current outline:\n\n{current}")
    if state["instruction"]:
        parts.append(f"Revision instruction:\n\n{state['instruction']}")
    return "\n\n".join(parts)


async def outline(
    state: ReporterState,
    writer: StreamWriter,
    config: Optional[RunnableConfig] = None,
) -> dict[str, Any]:
    """Propose or revise the report's section list.

    Two paths refuse without a model call, because neither needs one: an empty
    transcript is the Q5 case, and a spent revision budget is a fixed answer.
    Neither emits progress: both return immediately, and "Reading the
    conversation..." followed instantly by a refusal is a worse experience than
    no frame at all.

    The `writer` call is below both short-circuits and above the model call,
    which is where the wait actually is. It fires on the first draft *and on
    every revision round*, which is what makes a revise resume show progress:
    `classify` does not re-run on a resume, so nothing upstream would.

    `instruction` is cleared on every return. It is consumed by this node and
    must not survive into the next round: leaving it set would re-apply the
    previous revision on top of the next one.

    `config`, like `writer`, must be spelled exactly `RunnableConfig` or
    `Optional[RunnableConfig]`. Under `from __future__ import annotations`
    LangGraph matches the annotation as a string against that allow-list, so
    the PEP 604 `RunnableConfig | None` is silently never injected and the node
    runs with `config=None`.
    """
    if not state["transcript"].strip():
        logger.info("outline: refusing, empty transcript")
        return {"outline": [], "notice": NO_MATERIAL_NOTICE, "instruction": ""}
    if state["revisions"] > MAX_REVISION_ROUNDS:
        # Returns [] so `_after_outline` routes to END and the run *stops*.
        # Returning the outline unchanged would route back to `gate`, which
        # interrupts again — measured: the pause never resolves and `revisions`
        # grows without limit, so the "cap" would cap only the outline model
        # call, not the loop it was written to bound.
        logger.info("outline: stopping, %d revisions spent", state["revisions"])
        return {"outline": [], "notice": REVISION_CAP_NOTICE, "instruction": ""}

    writer(OUTLINE_PROGRESS)
    draft = await ainvoke_structured(
        OUTLINE_SYSTEM_PROMPT,
        [HumanMessage(_human_prompt(state))],
        OutlineDraft,
        config=config,
        settings=OUTLINE_LLM_SETTINGS,
    )
    sections = [" ".join(s.split()) for s in draft.sections if s.strip()]
    notice = " ".join(draft.notice.split())
    if not sections:
        # An empty list on a revision means the model declined it; keep what the
        # user already approved of rather than dropping the run to the refusal
        # path, which would discard the outline they were looking at.
        kept = list(state["outline"])
        logger.info("outline: no sections returned, kept %d", len(kept))
        return {
            "outline": kept,
            "notice": notice or NO_MATERIAL_NOTICE,
            "instruction": "",
        }
    logger.info("outline: %d sections, notice=%s", len(sections), bool(notice))
    return {"outline": sections, "notice": notice, "instruction": ""}
