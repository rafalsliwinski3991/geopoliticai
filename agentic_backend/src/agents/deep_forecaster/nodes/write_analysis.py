"""Writing the analysis (graph node 6): prose from the tally, never a new verdict."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from agents.deep_forecaster.config import WRITE_LLM_SETTINGS
from agents.deep_forecaster.consts.progress import REWRITE_LABEL, WRITE_LABEL
from agents.deep_forecaster.council import final_ballots
from agents.deep_forecaster.evidence import (
    render_ballot,
    render_claims,
    render_deadline,
    render_sources,
)
from agents.deep_forecaster.models import Analysis
from agents.deep_forecaster.prompts import RETRY_INSTRUCTIONS, WRITE_SYSTEM_PROMPT
from agents.deep_forecaster.state import ForecastRun, ForecastState
from llm import ainvoke_structured


async def write_analysis(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Write the overview and one section per claim from the council's record."""
    feedback = state.get("feedback")
    runtime.context.enter(
        REWRITE_LABEL if feedback else WRITE_LABEL, runtime.stream_writer
    )
    brief = _brief(state)
    if feedback:
        brief += "\n\n" + RETRY_INSTRUCTIONS.format(defect=feedback)
    analysis = await ainvoke_structured(
        WRITE_SYSTEM_PROMPT.format(today=render_deadline(runtime.context.today)),
        [HumanMessage(brief)],
        Analysis,
        settings=WRITE_LLM_SETTINGS,
    )
    return {"analysis": analysis}


def _brief(state: ForecastState) -> str:
    """Return the writer's input: claims, verdicts, final-round votes, and sources.

    A member that did not answer round 2 is marked, so the prose never
    describes its carried vote as a revision (correctness review).
    """
    verdicts = "\n".join(
        f"Claim {t.claim}: {t.verdict} ({t.votes_for} for, {t.against} against, "
        f"{t.unsure} unsure, of {t.voting} voting)"
        for t in state["tally"]
    )
    revised = state["ballots_round_2"]
    final = final_ballots(state["ballots_round_1"], revised)
    votes = "\n\n".join(
        f"Member {member}"
        f"{'' if member in revised else ' (did not answer round 2; its round-1 vote)'}"
        f":\n{render_ballot(ballot)}"
        for member, ballot in sorted(final.items())
    )
    return (
        f"Question: {state['question']}\n\nClaims:\n{render_claims(state['claims'])}"
        f"\n\nThe council's verdicts:\n{verdicts}\n\nFinal-round votes:\n{votes}"
        f"\n\nSources:\n\n{render_sources(state['sources'], urls=False)}"
    )
