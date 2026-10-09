"""The council's two rounds (graph nodes 3 and 4, brainstorm Q11)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from agents.deep_forecaster.config import COUNCIL, LIMITS
from agents.deep_forecaster.consts.progress import ROUND_LABEL
from agents.deep_forecaster.council import convene, round_one_view
from agents.deep_forecaster.evidence import (
    quoted_sources_by_claim,
    render_deadline,
    render_passages,
)
from agents.deep_forecaster.prompts import MEMBER_SYSTEM_PROMPT
from agents.deep_forecaster.state import ForecastRun, ForecastState


async def council_round_1(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Every member votes on every claim, independently and at once."""
    runtime.context.enter(ROUND_LABEL.format(round=1), runtime.stream_writer)
    messages = _messages(state, runtime.context, "")
    ballots = await convene(
        1,
        range(1, len(COUNCIL) + 1),
        lambda member: messages,
        claims=len(state["claims"]),
        quoted_by_claim=quoted_sources_by_claim(state["claims"]),
        quorum=LIMITS.quorum,
    )
    return {"ballots_round_1": ballots}


async def council_round_2(
    state: ForecastState, runtime: Runtime[ForecastRun]
) -> dict[str, Any]:
    """Each member who voted in round 1 reads the others' votes and votes again.

    No quorum here: a member that fails round 2 keeps its round-1 vote
    (`council.final_ballots`), so the council that voted in round 1 stands.
    """
    runtime.context.enter(ROUND_LABEL.format(round=2), runtime.stream_writer)
    first = state["ballots_round_1"]
    ballots = await convene(
        2,
        sorted(first),
        lambda member: _messages(state, runtime.context, round_one_view(member, first)),
        claims=len(state["claims"]),
        quoted_by_claim=quoted_sources_by_claim(state["claims"]),
        quorum=0,
    )
    return {"ballots_round_2": ballots}


def _messages(
    state: ForecastState, run: ForecastRun, addendum: str
) -> list[BaseMessage]:
    """Return one member's prompt: the claims with their passages, then `addendum` if any.

    Members read the passages, never the whole sources (user decision
    2026-10-01): about 10k tokens instead of ~100k.
    """
    evidence = (
        f"Question: {state['question']}\n\n"
        f"{render_passages(state['claims'], state['sources'])}"
    )
    if addendum:
        evidence = f"{evidence}\n\n{addendum}"
    return [
        SystemMessage(MEMBER_SYSTEM_PROMPT.format(today=render_deadline(run.today))),
        HumanMessage(evidence),
    ]
