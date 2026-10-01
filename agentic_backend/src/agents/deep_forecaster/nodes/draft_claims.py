"""Drafting the claims (graph node 2): one structured call over every source (Q27)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from agents.deep_forecaster.config import CLAIMS_LLM_SETTINGS, LIMITS
from agents.deep_forecaster.consts.progress import CLAIMS_LABEL
from agents.deep_forecaster.evidence import paragraphs, render_deadline, render_sources
from agents.deep_forecaster.prompts import DRAFT_CLAIMS_PROMPT
from agents.deep_forecaster.state import (
    Claim,
    DraftedClaims,
    ForecastRun,
    ForecastState,
)
from llm import ainvoke_structured
from models import LLMInvocationError, Source

logger = logging.getLogger(__name__)


async def draft_claims(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Draft 2-4 dated, checkable claims, each pointing at its evidence; check them in code."""
    runtime.context.enter(CLAIMS_LABEL, runtime.stream_writer)
    today = runtime.context.today
    drafted = await ainvoke_structured(
        DRAFT_CLAIMS_PROMPT.format(today=render_deadline(today)),
        [
            HumanMessage(
                f"Question: {state['question']}\n\nSources:\n\n"
                f"{render_sources(state['sources'])}"
            )
        ],
        DraftedClaims,
        settings=CLAIMS_LLM_SETTINGS,
    )
    return {
        "claims": checked_claims(drafted.claims, today=today, sources=state["sources"])
    }


def checked_claims(
    claims: list[Claim], *, today: date, sources: Sequence[Source]
) -> list[Claim]:
    """Return `claims` with each claim's passages tidied, or raise if a claim breaks a rule.

    The claims themselves are a hard error, never repaired (brainstorm §3:
    invalid claims are a 502): 2-4, distinct, all due after `today`. The
    passages are tidied instead (correctness review): a number that names no
    paragraph has no text a member could read, so it is left out, a repeat is
    listed once, and only the first `max_passages` are kept. A claim left
    with no passage at all is a 502. Every tidy is logged, so the smoke runs
    show how often the drafter miscounts.
    """
    if not LIMITS.min_claims <= len(claims) <= LIMITS.max_claims:
        raise LLMInvocationError(
            f"The forecast drafted {len(claims)} claims; it needs "
            f"{LIMITS.min_claims} to {LIMITS.max_claims}."
        )
    counts = [len(paragraphs(source.text)) for source in sources]
    seen: set[str] = set()
    checked = []
    for number, claim in enumerate(claims, start=1):
        key = " ".join(claim.statement.split()).casefold()
        if not key:
            raise LLMInvocationError("The forecast drafted an empty claim.")
        if key in seen:
            raise LLMInvocationError("The forecast drafted the same claim twice.")
        seen.add(key)
        if claim.deadline <= today:
            raise LLMInvocationError(
                "The forecast drafted a claim whose deadline is not in the future."
            )
        real = {
            (ref.source, ref.paragraph): ref
            for ref in claim.passages
            if 1 <= ref.source <= len(sources)
            and 1 <= ref.paragraph <= counts[ref.source - 1]
        }
        kept = list(real.values())[: LIMITS.max_passages]
        if not kept:
            raise LLMInvocationError(
                "The forecast drafted a claim with no passage its sources contain."
            )
        if len(kept) < len(claim.passages):
            logger.warning(
                "draft_claims: Claim %d kept %d of %d passages",
                number,
                len(kept),
                len(claim.passages),
            )
        checked.append(claim.model_copy(update={"passages": kept}))
    return checked
