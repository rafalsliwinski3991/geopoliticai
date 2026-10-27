"""Drafting the claims (graph node 2): one structured call over every source (Q27)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from agents.deep_forecaster.citations import links_in, paragraphs
from agents.deep_forecaster.config import CLAIMS_LLM_SETTINGS, LIMITS
from agents.deep_forecaster.consts.forecasters import FORECASTER_SOURCES
from agents.deep_forecaster.consts.progress import CLAIMS_LABEL
from agents.deep_forecaster.models import Claim, DraftedClaims
from agents.deep_forecaster.prompts import (
    DRAFT_CLAIMS_PROMPT,
    DRAFT_CLAIMS_RETRY_INSTRUCTIONS,
)
from agents.deep_forecaster.render import render_deadline, render_sources
from agents.deep_forecaster.state import ForecastRun, ForecastState
from models import Source
from services.llm import ainvoke_structured
from shared.errors import LLMInvocationError
from shared.tracing import start_span

logger = logging.getLogger(__name__)


async def draft_claims(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Draft 2-4 dated, checkable claims, each pointing at its evidence; check them in code."""
    runtime.context.enter(CLAIMS_LABEL, runtime.stream_writer)
    today = runtime.context.today
    prompt = DRAFT_CLAIMS_PROMPT.format(today=render_deadline(today))
    brief = (
        f"Question: {state['question']}\n\nSources:\n\n"
        f"{render_sources(state['sources'])}"
    )
    attempts = 0
    first_defect = ""
    last_defect = ""
    claims: list[Claim] | None = None
    with start_span("claim_draft") as span:
        try:
            while claims is None:
                attempts += 1
                drafted = await ainvoke_structured(
                    prompt,
                    [HumanMessage(brief)],
                    DraftedClaims,
                    settings=CLAIMS_LLM_SETTINGS,
                )
                try:
                    claims = checked_claims(
                        drafted.claims, today=today, sources=state["sources"]
                    )
                except LLMInvocationError as defect:
                    last_defect = str(defect)
                    first_defect = first_defect or last_defect
                    if attempts >= LIMITS.draft_attempts:
                        raise
                    logger.warning("draft_claims: redrafting once: %s", defect)
                    brief += "\n\n" + DRAFT_CLAIMS_RETRY_INSTRUCTIONS.format(
                        defect=last_defect
                    )
        finally:
            span.set_attributes(
                {
                    "claims.attempts": attempts,
                    "claims.first_defect": first_defect,
                    "claims.last_defect": last_defect,
                    "claims.redraft_fixed": claims is not None and attempts > 1,
                    "claims.kept": len(claims or []),
                }
            )
    _record_evidence_positions(claims, state["sources"])
    return {"claims": claims}


def _record_evidence_positions(claims: list[Claim], sources: Sequence[Source]) -> None:
    """Record where each cited paragraph sits in its page, and whether that page was cut.

    A position is paragraph / paragraph count, so 1.0 is a page's last kept
    paragraph. A page is cut when its text is exactly `max_source_chars`
    long (brainstorm 2026Oct13 Q10): no `Source` field records it.
    """
    refs = [ref for claim in claims for ref in claim.evidence]
    counts = [len(paragraphs(source.text)) for source in sources]
    with start_span("evidence_positions") as span:
        span.set_attributes(
            {
                "evidence.positions": [
                    ref.paragraph / counts[ref.source - 1] for ref in refs
                ],
                "evidence.on_cut_source": [
                    len(sources[ref.source - 1].text)
                    == FORECASTER_SOURCES.max_source_chars
                    for ref in refs
                ],
            }
        )


def checked_claims(
    claims: list[Claim], *, today: date, sources: Sequence[Source]
) -> list[Claim]:
    """Return `claims` with each claim's evidence refs tidied, or raise if a claim breaks a rule.

    The claims themselves are a hard error, never repaired (brainstorm §3:
    invalid claims are a 502): 2-4, distinct, all due after `today`. The
    evidence refs are tidied instead (correctness review): a number that names no
    paragraph has no text a member could read, so it is left out, a repeat is
    listed once, and only the first `max_passages` are kept. A claim left
    with no evidence ref at all is a 502. Every tidy is logged, so the smoke runs
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
        # The statement goes into the answer's heading as plain text: a link
        # in it would be a citation the forecast never read, and a newline
        # would inject a heading (review thread, #143).
        if "\n" in claim.statement or links_in(claim.statement):
            raise LLMInvocationError(
                "The forecast wrote a claim statement with a link or a line break."
            )
        if claim.deadline <= today:
            raise LLMInvocationError(
                f"The forecast drafted claim {number} with the deadline "
                f"{claim.deadline.isoformat()}, which is not after today "
                f"({today.isoformat()})."
            )
        real = {
            (ref.source, ref.paragraph): ref
            for ref in claim.evidence
            if 1 <= ref.source <= len(sources)
            and 1 <= ref.paragraph <= counts[ref.source - 1]
        }
        kept = list(real.values())[: LIMITS.max_passages]
        if not kept:
            raise LLMInvocationError(
                "The forecast drafted a claim with no passage its sources contain."
            )
        if len(kept) < len(claim.evidence):
            logger.warning(
                "draft_claims: Claim %d kept %d of %d evidence refs",
                number,
                len(kept),
                len(claim.evidence),
            )
        checked.append(claim.model_copy(update={"evidence": kept}))
    return checked
