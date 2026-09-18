"""The paused-thread intent classifier.

This is deliberately *not* a graph node. Its answer decides whether the delivery
layer sends `Command(resume=...)` or a fresh state input, so it must run before
the graph is invoked at all (brainstorm Q14). It therefore takes no `writer`:
there is no graph run in flight when it is called.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage

from agents.reporter.config import INTENT_LLM_SETTINGS
from agents.reporter.prompts import RESUME_INTENT_SYSTEM_PROMPT
from agents.reporter.state import ResumeIntent
from llm import ainvoke_structured

logger = logging.getLogger(__name__)


async def classify_resume_intent(text: str, pause: dict[str, Any]) -> ResumeIntent:
    """Sort one line typed at a paused gate into approve/revise/cancel/new_question."""
    sections = pause.get("outline") or []
    outline_block = "\n".join(f"{i}. {s}" for i, s in enumerate(sections, 1))
    human_prompt = (
        f"Outline awaiting a decision:\n\n{outline_block}\n\nUser typed:\n\n{text}"
    )
    decision = await ainvoke_structured(
        RESUME_INTENT_SYSTEM_PROMPT,
        [HumanMessage(human_prompt)],
        ResumeIntent,
        settings=INTENT_LLM_SETTINGS,
    )
    instruction = " ".join(decision.instruction.split())
    if decision.action == "revise" and not instruction:
        # A revise with nothing to apply would redraw the same outline and burn
        # a round. The user's own words are the honest fallback instruction.
        instruction = " ".join(text.split())
    logger.info("resume intent: %s", decision.action)
    return ResumeIntent(action=decision.action, instruction=instruction)
