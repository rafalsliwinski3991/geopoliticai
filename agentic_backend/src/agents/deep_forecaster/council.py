"""The council: neutral members, one per model vendor, voting in two rounds.

Brainstorm 2026Sep30 Q2, Q4, Q7, Q9, Q11, Q20, Q21, Q26. Every member gets the
same instructions and the same evidence. Members are "Member 1" … "Member 7"
wherever a reader or another member sees them; which model holds which seat
is logged for the operator and never shown (Q21).

Every seat is a paid model on OpenRouter. In round 1, a member whose first
answer cannot be counted — no ballot, a malformed one, or one
`validate_ballot` refuses — is asked once more with the problem named
(brainstorm 2026Oct19 Q1); code never edits a ballot. A provider outage
(a connection error, a 429, a 5xx, OpenRouter's HTTP 200 carrying an error,
or the member's time limit) is "outside" (Q2) and is not re-asked; a request
the provider refuses (another 4xx) is ours and is not re-asked either. Round 1
must keep a quorum after the re-asks (`LIMITS.quorum`, Q2b); below it is a
`QuorumError`. A member dropped in round 1 does not sit round 2, and a
round-1 voter that fails round 2 keeps its round-1 vote (`final_ballots`):
Delphi's second round revises a first vote, so a non-response there is "no
change", not a lost seat (plan review). Every member's outcome and every
round's counts are recorded on spans (`council_member`, `council_round`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import openai
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.constants import TAG_NOSTREAM
from pydantic import SecretStr, ValidationError

from agents.deep_forecaster.config import (
    COUNCIL,
    LIMITS,
    MEMBER_MAX_OUTPUT_TOKENS,
    Seat,
)
from agents.deep_forecaster.evidence import render_ballot
from agents.deep_forecaster.models import Ballot, Verdict
from agents.deep_forecaster.prompts import (
    REASK_NO_BALLOT,
    REASK_PROMPT,
    ROUND_TWO_INSTRUCTIONS,
)
from agents.deep_forecaster.state import ClaimTally
from llm import DEFAULT_MAX_RETRIES
from models import LLMInvocationError
from tracing import start_span

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MEMBER_TIME_LIMIT = "the member's time limit"
NO_BALLOT = "it returned no ballot"
UNREADABLE_BALLOT = "its ballot tool call could not be read"
# How much of a provider's error body is logged (F3), and of a malformed
# ballot's field errors the member reads back in its re-ask.
PROVIDER_ERROR_CHARS = 400
INVALID_ANSWER_CHARS = 300
# A 4xx at or above this is still an outage (429 rate limit); below it, the
# provider refused our request.
SERVER_ERROR_STATUS = 500
RATE_LIMIT_STATUS = 429
logger = logging.getLogger(__name__)

# Whose fault an attempt without a ballot was (brainstorm 2026Oct19 Q2, plan
# review): the model's answer, the provider's outage, or our request.
Fault = Literal["answer", "provider", "request"]


@dataclass(frozen=True)
class NoBallot:
    """Why one member has no countable ballot (brainstorm 2026Oct19 Q1, Q2).

    `fault` is "answer" when the answer broke a rule (re-asked once in round
    1), "provider" for an outage (never re-asked; "outside" by the
    brainstorm's rule), and "request" when the provider refused our request
    (never re-asked; ours). `rejected` is the refused ballot, quoted back in
    the re-ask, when the answer had one.
    """

    why: str
    fault: Fault
    rejected: Ballot | None = None

    @property
    def outside(self) -> bool:
        """Return whether the provider, not our code or request, failed."""
        return self.fault == "provider"


class QuorumError(LLMInvocationError):
    """Round 1 ended below quorum after the re-asks (a 502, as before).

    `outside` is True only when every member without a ballot failed on the
    provider's side (brainstorm 2026Oct19 Q2), so the live eval can tell a
    provider outage from a failure of our own rules.
    """

    def __init__(self, message: str, *, outside: bool) -> None:
        """Keep the message the API shows and whether the outage was the provider's."""
        super().__init__(message)
        self.outside = outside


def member_client(
    seat: Seat, model: str, *, max_retries: int = DEFAULT_MAX_RETRIES
) -> ChatOpenAI:
    """Return an OpenRouter chat client for `model` on `seat`; built per call.

    `model` is the seat's own model. Built at call time: `ChatOpenAI` cannot
    be constructed without a key. The openai SDK retries connection errors,
    timeouts, 408, 409, 429 and 5xx, never a 400; with every seat paid, those
    retries are the recovery for a transient failure (`_cast`).
    `_attempt`'s `asyncio.timeout` bounds each try, so a round
    still ends within one member timeout. No seat receives
    `parallel_tool_calls`, which `with_structured_output` sends and
    OpenRouter's non-OpenAI upstreams have been reported to reject (framework
    review).
    """
    return ChatOpenAI(
        model=model,
        max_completion_tokens=MEMBER_MAX_OUTPUT_TOKENS,
        timeout=LIMITS.member_seconds,
        max_retries=max_retries,
        streaming=False,
        reasoning_effort=seat.reasoning_effort,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        disabled_params={"parallel_tool_calls": None},
    )


def member_model(seat: Seat, model: str, *, max_retries: int) -> Any:
    """Return the ballot-producing chain for `model` on `seat`.

    Structured output goes through tool calling, which every roster model
    advertises (Q4). `TAG_NOSTREAM` keeps every ballot out of
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

    The reason names the claim and the numbers: the member reads it in its
    re-ask, and the operator in the log and on the `council_member` span
    (brainstorm 2026Oct19 Q1).
    """
    voted = sorted(vote.claim for vote in ballot.votes)
    if voted != list(range(1, claims + 1)):
        return (
            f"it must vote exactly once on each of claims 1 to {claims}; "
            f"it voted on {_list_numbers(voted) or 'none'}"
        )
    for vote in ballot.votes:
        claim = vote.claim
        reason = vote.reason.strip()
        if not reason:
            return f"claim {claim}'s reason is empty"
        if len(reason) > LIMITS.max_reason_chars:
            return (
                f"claim {claim}'s reason is {len(reason)} characters; "
                f"the limit is {LIMITS.max_reason_chars}"
            )
        if len(vote.evidence) > LIMITS.max_evidences:
            return (
                f"claim {claim} cites {len(vote.evidence)} sources; "
                f"the limit is {LIMITS.max_evidences}"
            )
        repeated = sorted({n for n in vote.evidence if vote.evidence.count(n) > 1})
        if repeated:
            return (
                f"claim {claim} cites source {_list_numbers(repeated)} more than once"
            )
        own = quoted_by_claim[claim]
        stray = sorted(set(vote.evidence) - own)
        if stray:
            return (
                f"claim {claim} cites source {_list_numbers(stray)}, which is not "
                f"among claim {claim}'s passages (it may cite "
                f"{_list_numbers(sorted(own))})"
            )
        if vote.stance != "unsure" and not vote.evidence:
            return f"claim {claim}'s '{vote.stance}' vote cites no source"
    return None


def _list_numbers(numbers: Sequence[int]) -> str:
    """Return numbers as a member reads them: "3", "3 and 5", "3, 5 and 9"."""
    words = [str(number) for number in numbers]
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"


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
    """Ask every member in `members` at once; return the counted ballots, or fail below `quorum`.

    A member may be re-asked once in round 1 (`_cast`). The round's counts go
    on a `council_round` span (brainstorm 2026Oct19, span rule).
    """
    started = time.monotonic()
    with start_span("council_round") as span:
        casts = await asyncio.gather(
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
            member: result
            for member, (result, _) in zip(members, casts, strict=True)
            if isinstance(result, Ballot)
        }
        dropped = [result for result, _ in casts if isinstance(result, NoBallot)]
        reasked = [result for result, attempts in casts if attempts > 1]
        span.set_attributes(
            {
                "council.round": round_number,
                "council.members_asked": len(casts),
                "council.ballots_counted": len(ballots),
                "council.reasked_members": len(reasked),
                "council.reask_fixed": sum(
                    1 for result in reasked if isinstance(result, Ballot)
                ),
                "council.dropped": len(dropped),
                "council.dropped_outside": sum(1 for d in dropped if d.outside),
                "council.dropped_request": sum(
                    1 for d in dropped if d.fault == "request"
                ),
                "council.quorum": quorum,
                "council.quorum_met": len(ballots) >= quorum,
                "council.seconds": round(time.monotonic() - started, 1),
            }
        )
    if len(ballots) < quorum:
        raise QuorumError(
            f"Only {len(ballots)} of {len(COUNCIL)} council members could vote in "
            f"round {round_number}; the council needs {quorum}.",
            outside=all(no_ballot.outside for no_ballot in dropped),
        )
    return ballots


async def _cast(
    round_number: int,
    member: int,
    messages: list[BaseMessage],
    *,
    claims: int,
    quoted_by_claim: Mapping[int, frozenset[int]],
) -> tuple[Ballot | NoBallot, int]:
    """Return one member's ballot, or why it has none, and how many tries it took.

    In round 1 a first answer that broke a rule is asked once more, with the
    problem and the refused ballot (brainstorm 2026Oct19 Q1). Round 2 is not
    re-asked: a member without a round-2 ballot keeps its round-1 vote, so a
    re-ask there buys no quorum (plan review). An outage or a refused request
    is never re-asked. Each try has its own member limit. Every outcome is
    logged with the model that answered and the elapsed seconds (the smoke
    runs' measure of per-seat latency, F3) and recorded on a `council_member`
    span.
    """
    seat = COUNCIL[member - 1]
    started = time.monotonic()
    with start_span("council_member") as span:
        first = await _attempt(
            seat, messages, claims=claims, quoted_by_claim=quoted_by_claim
        )
        first_seconds = time.monotonic() - started
        result, attempts = first, 1
        if (
            isinstance(first, NoBallot)
            and first.fault == "answer"
            and round_number == 1
        ):
            logger.warning(
                "council round %d: Member %d re-asked after %.0f s: %s: %s",
                round_number,
                member,
                first_seconds,
                seat.model,
                first.why,
            )
            result = await _attempt(
                seat,
                [*messages, HumanMessage(_write_reask(first))],
                claims=claims,
                quoted_by_claim=quoted_by_claim,
            )
            attempts = 2
        span.set_attributes(
            _describe_member(
                round_number,
                member,
                seat,
                first=first,
                result=result,
                attempts=attempts,
                first_seconds=first_seconds,
                seconds=time.monotonic() - started,
            )
        )
    if isinstance(result, Ballot):
        # One line per member, naming the model that voted (the smoke runs
        # measure per-seat latency and drop rates from these).
        logger.info(
            "council round %d: Member %d voted via %s after %.0f s",
            round_number,
            member,
            seat.model,
            time.monotonic() - started,
        )
    else:
        _dropped(round_number, member, f"{seat.model}: {result.why}", started)
    return result, attempts


async def _attempt(
    seat: Seat,
    messages: list[BaseMessage],
    *,
    claims: int,
    quoted_by_claim: Mapping[int, frozenset[int]],
) -> Ballot | NoBallot:
    """Ask the seat's model once, inside one member limit; return its counted ballot, or why not.

    The answer's fault is a ballot the parser cannot validate (pydantic
    `ValidationError`, `OutputParserException`), no ballot, or one
    `validate_ballot` refuses. A 4xx other than 429 is our request refused.
    Everything else is the provider's: the member limit, a 429 or 5xx the
    client's retries did not clear, a connection error, and OpenRouter's
    HTTP 200 carrying an error body, which langchain-openai raises as
    `ValueError`, `KeyError` or `TypeError` (`chat_models/base.py:1493-1506`).
    Cancellation by the wall cap is a `BaseException`, so it passes through.
    """
    member = COUNCIL.index(seat) + 1
    try:
        async with asyncio.timeout(LIMITS.member_seconds):
            answer = await member_model(
                seat, seat.model, max_retries=DEFAULT_MAX_RETRIES
            ).ainvoke(messages)
    except TimeoutError:
        return NoBallot(MEMBER_TIME_LIMIT, fault="provider")
    except (ValidationError, OutputParserException) as exc:
        return NoBallot(_describe_invalid(exc), fault="answer")
    except Exception as exc:  # noqa: BLE001 - every other failure is the provider's or our request's
        # The body, logged only: the smoke runs need to tell a rejected
        # parameter from a transient provider error (F3).
        logger.error(
            "council: Member %d's attempt on %s failed: %s: %s",
            member,
            seat.model,
            type(exc).__name__,
            str(exc)[:PROVIDER_ERROR_CHARS],
        )
        refused = (
            isinstance(exc, openai.APIStatusError)
            and exc.status_code < SERVER_ERROR_STATUS
            and exc.status_code != RATE_LIMIT_STATUS
        )
        return NoBallot(type(exc).__name__, fault="request" if refused else "provider")
    # `ainvoke` returns `Any`: narrow it before returning it as a `Ballot`
    # (mypy --strict refuses a returned `Any`). Invalid JSON arguments land
    # here too: the parser sees no tool call.
    if not isinstance(answer, Ballot):
        return NoBallot(NO_BALLOT, fault="answer")
    problem = validate_ballot(answer, claims=claims, quoted_by_claim=quoted_by_claim)
    if problem is not None:
        return NoBallot(problem, fault="answer", rejected=answer)
    return answer


def _describe_invalid(exc: ValidationError | OutputParserException) -> str:
    """Return a malformed ballot's problem as the member reads it, without URLs or its own input.

    `str(ValidationError)` carries the input and an errors.pydantic.dev link,
    which the member prompt forbids in its own text (plan review); the field
    path and message are enough, e.g. "votes.1.claim: Field required".
    """
    if isinstance(exc, ValidationError):
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False, include_input=False)
        )
        return f"its ballot is malformed: {details}"[:INVALID_ANSWER_CHARS]
    return UNREADABLE_BALLOT


def _write_reask(first: NoBallot) -> str:
    """Return the one re-ask: what was wrong, and the refused ballot when there was one."""
    rejected = (
        render_ballot(first.rejected) if first.rejected is not None else REASK_NO_BALLOT
    )
    return REASK_PROMPT.format(why=first.why, rejected=rejected)


def _describe_member(
    round_number: int,
    member: int,
    seat: Seat,
    *,
    first: Ballot | NoBallot,
    result: Ballot | NoBallot,
    attempts: int,
    first_seconds: float,
    seconds: float,
) -> dict[str, Any]:
    """Return the `council_member` span's attributes: who, how many tries, and the outcome.

    Which model holds which seat is operator-only (Q21): spans, like logs, sit
    behind Phoenix's login and never reach the reader.
    """
    attributes: dict[str, Any] = {
        "council.round": round_number,
        "council.member": member,
        "council.model": seat.model,
        "council.attempts": attempts,
        "council.reasked": attempts > 1,
        "council.first_problem": first.why if isinstance(first, NoBallot) else "",
        "council.seconds": round(seconds, 1),
        "council.first_attempt_seconds": round(first_seconds, 1),
    }
    if isinstance(result, Ballot):
        stances = [vote.stance for vote in result.votes]
        return attributes | {
            "council.outcome": "voted",
            "council.votes_for": stances.count("for"),
            "council.votes_against": stances.count("against"),
            "council.votes_unsure": stances.count("unsure"),
            "council.evidence_cited": sum(len(vote.evidence) for vote in result.votes),
            "council.reason_chars_max": max(
                (len(vote.reason.strip()) for vote in result.votes), default=0
            ),
        }
    return attributes | {
        "council.outcome": "kept_round_1" if round_number == 2 else "dropped",
        "council.drop_reason": result.why,
        "council.fault": result.fault,
        "council.outside": result.outside,
    }


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
