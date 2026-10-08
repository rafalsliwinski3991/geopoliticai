"""The council: neutral members, one per model vendor, voting in two rounds.

Brainstorm 2026Sep30 Q2, Q4, Q7, Q9, Q11, Q20, Q21, Q26. Every member gets the
same instructions and the same evidence. Members are "Member 1" … "Member 7"
wherever a reader or another member sees them; which model holds which seat
is logged for the operator and never shown (Q21).

Every seat is a paid model; a seat that fails — an error, its timeout, no
ballot, or a ballot `validate_ballot` refuses — has no ballot for that round,
and the client's own retries (429, 5xx, connection errors) are the recovery
(user decision 2026-10-08, ending the free-roster fallback of 2026-10-01).
Round 1 must keep a quorum (Q9, F7); below it the forecast is a hard error. A
member dropped in round 1 does not sit round 2, and a round-1 voter that fails
round 2 keeps its round-1 vote (`final_ballots`): Delphi's second round
revises a first vote, so a non-response there is "no change", not a lost seat
(plan review).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.constants import TAG_NOSTREAM

from agents.deep_forecaster.config import (
    COUNCIL,
    LIMITS,
    MEMBER_MAX_OUTPUT_TOKENS,
    Seat,
)
from agents.deep_forecaster.evidence import render_ballot
from agents.deep_forecaster.models import Ballot, Verdict
from agents.deep_forecaster.prompts import ROUND_TWO_INSTRUCTIONS
from agents.deep_forecaster.state import ClaimTally
from llm import DEFAULT_MAX_RETRIES
from models import LLMInvocationError

PROVIDER_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}
PROVIDER_KEY_ENV = {"gemini": "GEMINI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
logger = logging.getLogger(__name__)


def member_client(
    seat: Seat, model: str, *, max_retries: int = DEFAULT_MAX_RETRIES
) -> ChatOpenAI:
    """Return a chat client for `model` on `seat`'s endpoint; built per call.

    `model` is the seat's own model. Built at call time: `ChatOpenAI` cannot
    be constructed without a key. The openai SDK retries connection errors,
    timeouts, 408, 409, 429 and 5xx, never a 400; with every seat paid, those
    retries are the recovery for a transient failure (`_cast`).
    `_cast`'s `asyncio.timeout` bounds the attempt, so a round
    still ends within one member timeout. Non-OpenAI seats never receive
    `parallel_tool_calls`, which `with_structured_output` sends and Gemini's
    compatible endpoint has been reported to reject (framework review).
    """
    connection: dict[str, Any] = {}
    if seat.provider != "openai":
        connection = {
            "base_url": PROVIDER_BASE_URLS[seat.provider],
            "api_key": os.environ[PROVIDER_KEY_ENV[seat.provider]],
            "disabled_params": {"parallel_tool_calls": None},
        }
    return ChatOpenAI(
        model=model,
        max_completion_tokens=MEMBER_MAX_OUTPUT_TOKENS,
        timeout=LIMITS.member_seconds,
        max_retries=max_retries,
        streaming=False,
        reasoning_effort=seat.reasoning_effort,
        **connection,
    )


def member_model(seat: Seat, model: str, *, max_retries: int) -> Any:
    """Return the ballot-producing chain for `model` on `seat`'s endpoint.

    Structured output goes through tool calling, which every roster model
    advertises; five of seven seats do not advertise
    `structured_outputs` (Q4). `TAG_NOSTREAM` keeps every ballot out of
    `stream_mode="messages"`.
    """
    return (
        member_client(seat, model, max_retries=max_retries)
        .with_structured_output(Ballot, method="function_calling")
        .with_config(tags=[TAG_NOSTREAM])
    )


def validate_ballot(
    ballot: Ballot, *, claims: int, quoted_by_claim: Mapping[int, frozenset[int]]
) -> str | None:
    """Return why `ballot` cannot be counted, or None when it can (F3).

    `quoted_by_claim` holds, per claim, the numbers of the sources whose
    passages that claim quotes (`evidence.quoted_sources_by_claim`): a vote on
    claim 1 may cite only what claim 1 quotes, evidence from another claim's
    sources is evidence the vote was not given, and a repeated number counts
    once (review thread, #142).
    """
    if sorted(vote.claim for vote in ballot.votes) != list(range(1, claims + 1)):
        return "not exactly one vote per claim"
    for vote in ballot.votes:
        reason = vote.reason.strip()
        if not reason:
            return "an empty reason"
        if len(reason) > LIMITS.max_reason_chars:
            return "a reason over the length limit"
        if len(vote.evidence) > LIMITS.max_evidences:
            return "more evidence than the limit"
        if len(set(vote.evidence)) != len(vote.evidence):
            return "a repeated evidence number"
        own = quoted_by_claim[vote.claim]
        if any(number not in own for number in vote.evidence):
            return "evidence it was not given"
        if vote.stance != "unsure" and not vote.evidence:
            return f"a '{vote.stance}' vote without evidence"
    return None


def count_votes(claims: int, ballots: Mapping[int, Ballot]) -> list[ClaimTally]:
    """Tally the final round: 2/3 of those voting, rounded up, decides (Q7)."""
    voting = len(ballots)
    threshold = -(-2 * voting // 3)
    tallies = []
    for number in range(1, claims + 1):
        stances = [
            vote.stance
            for ballot in ballots.values()
            for vote in ballot.votes
            if vote.claim == number
        ]
        votes_for, against = stances.count("for"), stances.count("against")
        verdict: Verdict = (
            "ACCEPTED"
            if votes_for >= threshold
            else "REJECTED"
            if against >= threshold
            else "UNRESOLVED"
        )
        tallies.append(
            ClaimTally(
                claim=number,
                verdict=verdict,
                votes_for=votes_for,
                against=against,
                unsure=stances.count("unsure"),
                voting=voting,
            )
        )
    return tallies


def final_ballots(
    first: Mapping[int, Ballot], second: Mapping[int, Ballot]
) -> dict[int, Ballot]:
    """Return each round-1 voter's latest ballot: its revision, else its first vote."""
    return {member: second.get(member, ballot) for member, ballot in first.items()}


def round_one_view(member: int, ballots: Mapping[int, Ballot]) -> str:
    """Return what `member` reads in round 2: its own votes, then the others' (Q11)."""
    parts = [
        ROUND_TWO_INSTRUCTIONS,
        "",
        "Your round-1 votes:",
        render_ballot(ballots[member]),
    ]
    for other in sorted(ballots):
        if other != member:
            parts += ["", f"Member {other}:", render_ballot(ballots[other])]
    return "\n".join(parts)


async def convene(
    round_number: int,
    members: Sequence[int],
    messages_for: Callable[[int], list[BaseMessage]],
    *,
    claims: int,
    quoted_by_claim: Mapping[int, frozenset[int]],
    quorum: int,
) -> dict[int, Ballot]:
    """Ask every member in `members` at once; return the counted ballots, or fail below `quorum`."""
    results = await asyncio.gather(
        *(
            _cast(
                round_number,
                member,
                messages_for(member),
                claims=claims,
                quoted_by_claim=quoted_by_claim,
            )
            for member in members
        )
    )
    ballots = {
        member: ballot
        for member, ballot in zip(members, results, strict=True)
        if ballot is not None
    }
    if len(ballots) < quorum:
        raise LLMInvocationError(
            f"Only {len(ballots)} of {len(COUNCIL)} council members could vote in "
            f"round {round_number}; the council needs {quorum}."
        )
    return ballots


async def _cast(
    round_number: int,
    member: int,
    messages: list[BaseMessage],
    *,
    claims: int,
    quoted_by_claim: Mapping[int, frozenset[int]],
) -> Ballot | None:
    """Return one member's counted ballot, or None when it has none this round.

    One attempt on the seat's own model, with the client's retries (user
    decision 2026-10-08). Every outcome is logged with the model that
    answered and the elapsed seconds, the smoke runs' measure of
    per-seat latency (F3).
    """
    seat = COUNCIL[member - 1]
    started = time.monotonic()
    try:
        async with asyncio.timeout(LIMITS.member_seconds):
            ballot, why = await _attempt(
                seat,
                messages,
                claims=claims,
                quoted_by_claim=quoted_by_claim,
            )
            if ballot is not None:
                # One line per member, naming the model that voted (the smoke
                # runs measure per-seat latency and drop rates from these).
                logger.info(
                    "council round %d: Member %d voted via %s after %.0f s",
                    round_number,
                    member,
                    seat.model,
                    time.monotonic() - started,
                )
                return ballot
            failure = f"{seat.model}: {why}"
    except TimeoutError:
        failure = f"{seat.model}: the member's time limit"
    _dropped(round_number, member, failure, started)
    return None


async def _attempt(
    seat: Seat,
    messages: list[BaseMessage],
    *,
    claims: int,
    quoted_by_claim: Mapping[int, frozenset[int]],
) -> tuple[Ballot | None, str]:
    """Ask the seat's model once (with the client's retries); return its counted ballot, or None and why not.

    Cancellation by the member's own timeout or by
    the wall cap is a `BaseException`, so it passes through.
    """
    try:
        ballot = await member_model(
            seat, seat.model, max_retries=DEFAULT_MAX_RETRIES
        ).ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 - a failed attempt has no ballot (Q9)
        # The body, logged only: the smoke runs need to tell a rejected
        # parameter from a transient provider error (F3).
        logger.error(
            "council: Member %d's attempt on %s failed: %s: %s",
            COUNCIL.index(seat) + 1,
            seat.model,
            type(exc).__name__,
            str(exc)[:400],
        )
        return None, type(exc).__name__
    # `ainvoke` returns `Any`: narrow it before returning it as a `Ballot`
    # (mypy --strict refuses a returned `Any`).
    if not isinstance(ballot, Ballot):
        return None, "no ballot"
    problem = validate_ballot(ballot, claims=claims, quoted_by_claim=quoted_by_claim)
    if problem is not None:
        return None, problem
    return ballot, ""


def _dropped(round_number: int, member: int, why: str, started: float) -> None:
    """Log a member without a ballot this round, with its model's failure (Q21: logs only)."""
    outcome = "kept its round-1 vote" if round_number == 2 else "dropped"
    logger.warning(
        "council round %d: Member %d %s after %.0f s: %s",
        round_number,
        member,
        outcome,
        time.monotonic() - started,
        why,
    )
