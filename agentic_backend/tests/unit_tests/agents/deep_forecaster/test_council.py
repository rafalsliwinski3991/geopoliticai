"""Unit tests for `agents.deep_forecaster.council`."""

import asyncio
import dataclasses
import importlib
import time
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

import agents.deep_forecaster.config as config
from agents.deep_forecaster.config import COUNCIL, LIMITS
from agents.deep_forecaster.council import (
    _cast,
    convene,
    count_votes,
    final_ballots,
    member_client,
    round_one_view,
    validate_ballot,
)
from agents.deep_forecaster.models import Ballot, Stance, Vote
from llm import DEFAULT_MAX_RETRIES
from models import LLMInvocationError
from unit_tests.agents.deep_forecaster.conftest import (
    HANG,
    OPENROUTER_CHAT_URL,
    Delayed,
    ScriptedCouncil,
    ballot,
    provider_error,
    request_error,
    shorten_limit,
)

council_module: Any = importlib.import_module("agents.deep_forecaster.council")


# What claim 1 and claim 2 quote, per claim: tests give every vote the
# evidence the claims themselves carry (review thread, #142).
QUOTED_BY_CLAIM = {1: frozenset({1, 3}), 2: frozenset({1, 3})}

# A ballot citing source 2 on claim 1, which claim 1's passages do not quote
# (they quote sources 1 and 3): the refusal every re-ask test reads.
STRAY_BALLOT = ballot(["for", "unsure"], evidence={1: [2]})
STRAY_WHY = (
    "claim 1 cites source 2, which is not among claim 1's passages "
    "(it may cite 1 and 3)"
)
SHORT_MEMBER_SECONDS = 0.05
SLOW_TRY_SECONDS = 0.5
MEMBER_LIMIT_SECONDS = 0.75


def _valid() -> Ballot:
    return ballot(["for", "unsure"], evidence={1: [1]})


def _rate_limited() -> openai.RateLimitError:
    """An OpenRouter 429 that outlived the client's retries: an outage."""
    return openai.RateLimitError(
        "rate limited",
        response=httpx.Response(
            429, request=httpx.Request("POST", OPENROUTER_CHAT_URL)
        ),
        body=None,
    )


def _connection_lost() -> openai.APIConnectionError:
    """A connection error on the way to OpenRouter: an outage."""
    return openai.APIConnectionError(request=httpx.Request("POST", OPENROUTER_CHAT_URL))


def _http_200_error_body() -> ValueError:
    """OpenRouter's HTTP 200 carrying an error body, which langchain-openai
    raises as `ValueError` (`chat_models/base.py:1493-1506`): an outage."""
    return ValueError(
        "Error code: 502 - {'error': {'message': 'Upstream overloaded.'}}"
    )


def _malformed_ballot_error() -> ValidationError:
    """The `ValidationError` pydantic raises for a ballot whose one vote lacks every field."""
    try:
        Ballot.model_validate({"votes": [{"claim": 1}]})
    except ValidationError as exc:
        return exc
    raise AssertionError("the malformed ballot validated")


def _span_by_name(captured: InMemorySpanExporter, name: str) -> ReadableSpan:
    matches = [
        span
        for span in captured.get_finished_spans()
        if span.name == name and span.attributes is not None
    ]
    assert len(matches) == 1, f"expected exactly one {name} span, got {len(matches)}"
    return matches[0]


class TestValidateBallot:
    def test_a_well_formed_ballot_counts(self) -> None:
        assert (
            validate_ballot(_valid(), claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_an_unsure_vote_needs_no_evidence(self) -> None:
        ballot_ = ballot(["unsure", "unsure"], evidence={})
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    @pytest.mark.parametrize(
        "ballot_, why",
        [
            pytest.param(
                ballot(["for"]),
                "it must vote exactly once on each of claims 1 to 2; it voted on 1",
                id="a claim missing",
            ),
            pytest.param(
                ballot(["for", "against", "unsure"]),
                "it must vote exactly once on each of claims 1 to 2; it voted on 1, 2 and 3",
                id="a claim too many",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: []}),
                "claim 1's 'for' vote cites no source",
                id="for without evidence",
            ),
            pytest.param(
                ballot(["against", "unsure"], evidence={1: []}),
                "claim 1's 'against' vote cites no source",
                id="against without evidence",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [2]}),
                "claim 1 cites source 2, which is not among claim 1's passages "
                "(it may cite 1 and 3)",
                id="another claim's source",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [9]}),
                "claim 1 cites source 9, which is not among claim 1's passages "
                "(it may cite 1 and 3)",
                id="a source never quoted",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [1, 3, 2, 3, 2, 1]}),
                "claim 1 cites 6 sources; the limit is 5",
                id="too many sources",
            ),
            pytest.param(
                ballot(["for", "unsure"], evidence={1: [1, 1, 3, 3]}),
                "claim 1 cites source 1 and 3 more than once",
                id="a repeated source",
            ),
        ],
    )
    def test_refusals(self, ballot_: Ballot, why: str) -> None:
        """A refusal names the claim and the numbers: the member reads it in its
        re-ask, and the operator in the log and on the `council_member` span."""
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) == why
        )

    def test_an_empty_reason(self) -> None:
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason="   ", evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
            == "claim 1's reason is empty"
        )

    def test_a_reason_over_the_limit(self) -> None:
        long = "r" * 601
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason=long, evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
            == "claim 1's reason is 601 characters; the limit is 600"
        )

    def test_a_reason_carrying_a_url_is_accepted(self) -> None:
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="See https://x.example/a.",
                    evidence=[1],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_a_reason_exactly_at_the_limit_is_accepted(self) -> None:
        """The limit is a limit, not one past it: a reason of exactly
        `max_reason_chars` characters counts (review thread)."""
        # Arrange
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="r" * LIMITS.max_reason_chars,
                    evidence=[1],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        # Act + Assert
        assert (
            validate_ballot(ballot_, claims=2, quoted_by_claim=QUOTED_BY_CLAIM) is None
        )

    def test_evidences_exactly_at_the_limit_are_accepted(self) -> None:
        """The limit is a limit, not one past it: exactly `max_evidences`
        distinct sources the claim quotes count (review thread)."""
        # Arrange: claim 1 quotes five sources, so a vote may cite all five.
        all_quoted = {
            1: frozenset({1, 2, 3, 4, 5}),
            2: frozenset({1, 3}),
        }
        ballot_ = Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance="for",
                    reason="ok",
                    evidence=[1, 2, 3, 4, 5],
                ),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        # Act + Assert
        assert validate_ballot(ballot_, claims=2, quoted_by_claim=all_quoted) is None


def _votes_on_one_claim(members: int, stances: list[str]) -> dict[int, Ballot]:
    """`members` ballots; member n votes stances[n-1] on Claim 1."""
    return {
        member: Ballot(
            votes=[
                Vote(
                    claim=1,
                    stance=cast(Stance, stance),
                    reason="r.",
                    evidence=[] if stance == "unsure" else [1],
                )
            ]
        )
        for member, stance in zip(range(1, members + 1), stances, strict=True)
    }


class TestCountVotes:
    def test_five_of_seven_for_is_accepted(self) -> None:
        tally = count_votes(1, _votes_on_one_claim(7, ["for"] * 5 + ["unsure"] * 2))
        assert tally[0].verdict == "ACCEPTED"

    def test_four_of_seven_for_is_unresolved(self) -> None:
        # 4 of 7: threshold ceil(14/3) = 5 → UNRESOLVED
        tally = count_votes(
            1, _votes_on_one_claim(7, ["for"] * 4 + ["against"] + ["unsure"] * 2)
        )
        assert tally[0].verdict == "UNRESOLVED"

    def test_five_of_seven_against_is_rejected(self) -> None:
        tally = count_votes(1, _votes_on_one_claim(7, ["against"] * 5 + ["unsure"] * 2))
        assert tally[0].verdict == "REJECTED"

    def test_four_of_six_for_is_accepted(self) -> None:
        # 6 voting: threshold ceil(12/3) = 4
        tally = count_votes(
            1, _votes_on_one_claim(6, ["for"] * 4 + ["against", "unsure"])
        )
        assert tally[0].verdict == "ACCEPTED"

    def test_three_of_six_for_is_unresolved(self) -> None:
        tally = count_votes(
            1, _votes_on_one_claim(6, ["for"] * 3 + ["against"] * 2 + ["unsure"])
        )
        assert tally[0].verdict == "UNRESOLVED"

    def test_four_of_five_for_is_accepted_and_three_is_not(self) -> None:
        four = count_votes(1, _votes_on_one_claim(5, ["for"] * 4 + ["unsure"]))
        three = count_votes(
            1, _votes_on_one_claim(5, ["for"] * 3 + ["against", "unsure"])
        )
        assert four[0].verdict == "ACCEPTED"
        assert three[0].verdict == "UNRESOLVED"

    def test_the_counts_per_stance_are_right(self) -> None:
        ballots = {
            1: ballot(["for", "unsure"]),
            2: ballot(["against", "for"]),
            3: ballot(["unsure", "unsure"]),
        }
        tally = count_votes(2, ballots)
        assert (
            tally[0].votes_for == 1 and tally[0].against == 1 and tally[0].unsure == 1
        )
        assert tally[0].voting == 3
        assert tally[1].votes_for == 1 and tally[1].unsure == 2


class TestRoundOneView:
    def test_it_shows_everyone_but_the_reader(self) -> None:
        ballots = {member: ballot(["for", "unsure"]) for member in range(1, 5)}
        view = round_one_view(3, ballots)
        assert view.startswith(
            "Round 2. Below are your own round-1 votes, then the other members' "
        )
        assert "Your round-1 votes:" in view
        assert "Member 1:" in view and "Member 2:" in view and "Member 4:" in view
        assert "Member 3:" not in view
        for seat in COUNCIL:
            assert seat.model not in view


@pytest.mark.anyio
async def test_a_ballot_that_breaks_a_rule_counts_after_one_reask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In round 1 a member whose first answer broke a rule is asked once more
    (brainstorm 2026Oct19 Q1): the fixed ballot counts, and the seat is kept."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT, _valid()]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert result == _valid()
    assert attempts == 2
    assert council.calls(3) == 2


@pytest.mark.anyio
async def test_the_reask_names_the_problem_and_quotes_the_ballot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-ask carries the rule the ballot broke and the refused ballot
    itself, so the member can fix its own answer; code never edits a ballot
    (brainstorm 2026Oct19 Q1). The first try's messages — the member's rules
    and the passages — are carried into the re-ask, so the member answers
    with the same evidence in front of it."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT, _valid()]})
    council.install(monkeypatch)
    messages = [SystemMessage("the member's rules"), HumanMessage("the passages")]
    # Act
    await _cast(1, 3, messages, claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    reask = council.sent[3][1][-1]
    assert isinstance(reask, HumanMessage)
    text = str(reask.content)
    assert STRAY_WHY in text
    assert "Claim 1: for — Reason 1. (Sources 2)" in text
    # The re-ask's message list keeps the first try's messages, then the re-ask.
    assert council.sent[3][1][:-1] == messages


@pytest.mark.anyio
async def test_a_ballot_broken_twice_is_dropped_without_a_third_try(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-ask is spent once (Q1): a member whose second ballot breaks a
    rule too is dropped, and no third question goes out."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT, STRAY_BALLOT]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert isinstance(result, council_module.NoBallot)
    assert result.fault == "answer"
    assert attempts == 2
    assert council.calls(3) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "first_reply",
    [
        pytest.param(None, id="no tool call"),
        pytest.param(_malformed_ballot_error(), id="malformed ballot"),
        pytest.param(
            OutputParserException("No valid tool call was found."), id="unknown tool"
        ),
    ],
)
async def test_an_answer_without_a_ballot_is_reasked(
    first_reply: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An answer that cannot be read as a ballot — no tool call, a malformed
    one, an unknown tool — broke a rule, so round 1 asks once more (Q1)."""
    # Arrange
    council = ScriptedCouncil({3: [first_reply, _valid()]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert result == _valid()
    assert attempts == 2
    assert council.calls(3) == 2


@pytest.mark.anyio
async def test_a_reask_meeting_an_outage_carries_the_later_fault_not_outside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-ask can meet an outage after an answer fault: the `fault` is the
    second try's, but `outside` stays false — the member's first answer broke
    a rule, so the drop is not purely the provider's (review thread)."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT, provider_error()]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert isinstance(result, council_module.NoBallot)
    assert result.fault == "provider"
    assert result.outside is False
    assert attempts == 2
    assert council.calls(3) == 2


@pytest.mark.anyio
async def test_a_malformed_ballot_is_described_without_urls_or_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed ballot's field path and message are all the member reads:
    `str(ValidationError)` carries the input and an errors.pydantic.dev link,
    which the member prompt forbids in its own text (plan review)."""
    # Arrange
    council = ScriptedCouncil({3: [_malformed_ballot_error(), _valid()]})
    council.install(monkeypatch)
    # Act
    await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    reask = str(council.sent[3][1][-1].content)
    assert "votes.1.stance: Field required" in reask
    assert "errors.pydantic.dev" not in reask
    assert "input_value" not in reask


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("first_reply", "member_seconds"),
    [
        pytest.param(provider_error(), None, id="server error"),
        pytest.param(_rate_limited(), None, id="rate limited"),
        pytest.param(provider_error(408), None, id="408 request timeout"),
        pytest.param(provider_error(409), None, id="409 conflict"),
        pytest.param(_connection_lost(), None, id="connection lost"),
        pytest.param(_http_200_error_body(), None, id="HTTP 200 with an error body"),
        pytest.param(HANG, SHORT_MEMBER_SECONDS, id="member time limit"),
    ],
)
async def test_an_outage_is_not_reasked(
    first_reply: Any,
    member_seconds: float | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outage — a 5xx, a 429, a connection error, OpenRouter's HTTP 200
    carrying an error body, or the member's time limit — is the provider's
    fault ("outside", Q2): re-asking a dead provider buys nothing."""
    # Arrange
    council = ScriptedCouncil({3: [first_reply]})
    council.install(monkeypatch)
    if member_seconds is not None:
        shorten_limit(monkeypatch, "council", member_seconds=member_seconds)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert isinstance(result, council_module.NoBallot)
    assert result.fault == "provider"
    assert result.outside is True
    assert attempts == 1
    assert council.calls(3) == 1


@pytest.mark.anyio
async def test_a_refused_request_is_ours_and_not_reasked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4xx below 500 (a rejected parameter, a retired model) refused our
    request: re-asking the same request cannot help, and the fault is ours."""
    # Arrange
    council = ScriptedCouncil({3: [request_error()]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert isinstance(result, council_module.NoBallot)
    assert result.fault == "request"
    assert result.outside is False
    assert attempts == 1
    assert council.calls(3) == 1


@pytest.mark.anyio
async def test_a_round_two_answer_is_not_reasked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 is never re-asked: a member without a round-2 ballot keeps its
    round-1 vote, so a re-ask there buys no quorum (plan review)."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT]})
    council.install(monkeypatch)
    # Act
    result, attempts = await _cast(2, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert isinstance(result, council_module.NoBallot)
    assert result.fault == "answer"
    assert attempts == 1
    assert council.calls(3) == 1


@pytest.mark.anyio
async def test_the_reask_gets_its_own_member_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each try carries the member limit on its own: a first try that used up
    its time does not eat the re-ask's, or one slow answer would cost the seat."""
    # Arrange
    council = ScriptedCouncil(
        {
            3: [
                Delayed(SLOW_TRY_SECONDS, STRAY_BALLOT),
                Delayed(SLOW_TRY_SECONDS, _valid()),
            ]
        }
    )
    council.install(monkeypatch)
    shorten_limit(monkeypatch, "council", member_seconds=MEMBER_LIMIT_SECONDS)
    # Act
    result, attempts = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert: 0.5 s + 0.5 s = 1 s is over the 0.75 s limit, and both try.
    assert result == _valid()
    assert attempts == 2


@pytest.mark.anyio
async def test_a_reask_is_logged_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The re-ask's warning names the member and the rule broken, with the
    model that answered: the smoke runs read per-seat behaviour from the log (F3)."""
    # Arrange
    import logging

    caplog.set_level(logging.WARNING, logger=council_module.__name__)
    council = ScriptedCouncil({3: [STRAY_BALLOT, _valid()]})
    council.install(monkeypatch)
    # Act
    await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    assert "Member 3 re-asked" in caplog.text
    assert STRAY_WHY in caplog.text


@pytest.mark.anyio
async def test_a_reask_quotes_the_ballot_without_its_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refused ballot is quoted back with its links removed (a reason is
    untrusted model text): a URL in it must not reach the member's next prompt
    to be echoed into the round-2 view."""
    # Arrange
    linked = Ballot(
        votes=[
            Vote(
                claim=1,
                stance="for",
                reason="See https://x.example/a.",
                evidence=[2],
            ),
            Vote(claim=2, stance="unsure", reason="Thin.", evidence=[]),
        ]
    )
    council = ScriptedCouncil({3: [linked, _valid()]})
    council.install(monkeypatch)
    # Act
    await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    reask = str(council.sent[3][1][-1].content)
    assert "(link removed)" in reask
    assert "https://x.example/a" not in reask


@pytest.mark.anyio
async def test_four_ballots_are_a_council(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three seats down to an outage still leave four valid ballots: four is
    the quorum (user decision 2026-10-19, brainstorm 2026Oct19 Q2b)."""
    # Arrange
    council = ScriptedCouncil({member: [provider_error()] for member in (1, 2, 3)})
    council.install(monkeypatch)
    # Act
    ballots = await convene(
        1,
        range(1, 8),
        lambda member: [],
        claims=2,
        quoted_by_claim=QUOTED_BY_CLAIM,
        quorum=LIMITS.quorum,
    )
    # Assert
    assert set(ballots) == {4, 5, 6, 7}


@pytest.mark.anyio
async def test_three_ballots_are_below_quorum(monkeypatch: pytest.MonkeyPatch) -> None:
    """Four seats down leave three ballots, below the quorum of 4: a
    `QuorumError` (a 502) stops the forecast before any analysis is written."""
    # Arrange
    council = ScriptedCouncil({member: [provider_error()] for member in (4, 5, 6, 7)})
    council.install(monkeypatch)
    # Act + Assert
    with pytest.raises(council_module.QuorumError) as raised:
        await convene(
            1,
            range(1, 8),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=LIMITS.quorum,
        )
    assert str(raised.value) == (
        "Only 3 of 7 council members could vote in round 1; the council needs 4."
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scripts", "outside"),
    [
        pytest.param(
            {member: [provider_error()] for member in (4, 5, 6, 7)},
            True,
            id="every drop an outage",
        ),
        pytest.param(
            {
                4: [provider_error()],
                5: [provider_error()],
                6: [provider_error()],
                7: [request_error()],
            },
            False,
            id="one drop a refused request",
        ),
        pytest.param(
            {
                4: [provider_error()],
                5: [provider_error()],
                6: [provider_error()],
                7: [STRAY_BALLOT, STRAY_BALLOT],
            },
            False,
            id="one drop broke a rule twice",
        ),
        pytest.param(
            {
                4: [provider_error()],
                5: [provider_error()],
                6: [provider_error()],
                7: [STRAY_BALLOT, provider_error()],
            },
            False,
            id="a re-ask met an outage after an answer fault",
        ),
    ],
)
async def test_a_quorum_error_is_outside_only_when_every_drop_was_an_outage(
    scripts: dict[int, list[Any]],
    outside: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`QuorumError.outside` tells the live eval a provider outage from a
    failure of our own rules (Q2): true only when every member without a
    ballot failed on the provider's side."""
    # Arrange
    council = ScriptedCouncil(scripts)
    council.install(monkeypatch)
    # Act + Assert
    with pytest.raises(council_module.QuorumError) as raised:
        await convene(
            1,
            range(1, 8),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=LIMITS.quorum,
        )
    assert raised.value.outside is outside


@pytest.mark.anyio
async def test_a_reasked_member_span_records_both_tries(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The `council_member` span records both tries of a re-ask that worked —
    who answered, how many tries, the first answer's problem, the vote's shape
    — so a Phoenix trace alone explains the seat's history (span rule)."""
    # Arrange
    council = ScriptedCouncil({3: [STRAY_BALLOT, _valid()]})
    council.install(monkeypatch)
    # Act
    await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    span = _span_by_name(captured_spans, "council_member")
    attributes = span.attributes
    assert attributes is not None
    assert attributes["council.round"] == 1
    assert attributes["council.member"] == 3
    assert attributes["council.model"] == COUNCIL[2].model
    assert attributes["council.attempts"] == 2
    assert attributes["council.reasked"] is True
    assert attributes["council.first_problem"] == STRAY_WHY
    assert attributes["council.outcome"] == "voted"
    assert attributes["council.votes_for"] == 1
    assert attributes["council.votes_unsure"] == 1
    assert attributes["council.evidence_cited"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("round_number", "first_reply", "outcome", "fault"),
    [
        pytest.param(1, provider_error(), "dropped", "provider", id="round 1 outage"),
        pytest.param(
            2,
            provider_error(),
            "kept_round_1",
            "provider",
            id="round 2 keeps its vote",
        ),
        pytest.param(1, request_error(), "dropped", "request", id="refused request"),
    ],
)
async def test_a_dropped_member_span_records_whose_fault_it_was(
    round_number: int,
    first_reply: Any,
    outcome: str,
    fault: str,
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """A member left without a ballot has the drop recorded on its
    `council_member` span with the outcome and whose fault it was (Q2, span
    rule); `council.outside` is dropped as a derived duplicate of
    `council.fault` (review thread)."""
    # Arrange
    council = ScriptedCouncil({3: [first_reply]})
    council.install(monkeypatch)
    # Act
    await _cast(round_number, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    # Assert
    span = _span_by_name(captured_spans, "council_member")
    attributes = span.attributes
    assert attributes is not None
    assert attributes["council.outcome"] == outcome
    assert attributes["council.fault"] == fault
    assert attributes["council.attempts"] == 1


@pytest.mark.anyio
async def test_the_round_span_counts_ballots_reasks_and_drops(
    monkeypatch: pytest.MonkeyPatch,
    captured_spans: InMemorySpanExporter,
) -> None:
    """The `council_round` span counts the round's ballots, re-asks and drops
    with the quorum verdict, so a trace alone explains a round (span rule)."""
    # Arrange: member 2's first ballot is fixed by its re-ask; member 3 is down.
    council = ScriptedCouncil({2: [STRAY_BALLOT, _valid()], 3: [provider_error()]})
    council.install(monkeypatch)
    # Act
    ballots = await convene(
        1,
        range(1, 8),
        lambda member: [],
        claims=2,
        quoted_by_claim=QUOTED_BY_CLAIM,
        quorum=LIMITS.quorum,
    )
    # Assert
    assert set(ballots) == {1, 2, 4, 5, 6, 7}
    span = _span_by_name(captured_spans, "council_round")
    attributes = span.attributes
    assert attributes is not None
    assert attributes["council.round"] == 1
    assert attributes["council.members_asked"] == 7
    assert attributes["council.ballots_counted"] == 6
    assert attributes["council.reasked_members"] == 1
    assert attributes["council.reask_fixed"] == 1
    assert attributes["council.dropped"] == 1
    assert attributes["council.dropped_outside"] == 1
    assert attributes["council.dropped_request"] == 0
    assert attributes["council.quorum"] == 4
    assert attributes["council.quorum_met"] is True


class TestConvene:
    def _fakes(
        self, monkeypatch: pytest.MonkeyPatch, behavior: dict[str, Any]
    ) -> dict[str, int]:
        """Patch `member_model` with fakes keyed by model id."""
        calls: dict[str, int] = {}

        class _Fake:
            def __init__(self, model: str) -> None:
                self.model = model

            async def ainvoke(self, messages: Any) -> Any:
                calls[self.model] = calls.get(self.model, 0) + 1
                action = behavior.get(self.model, "ok")
                if action == "raise":
                    raise RuntimeError("dead")
                if action == "slow":
                    await asyncio.sleep(0.2)
                if action == "invalid":
                    return ballot(["unsure"], evidence={1: [7]})
                if action == "none":
                    return None
                return behavior.get("ballot") or ballot(["for", "unsure"])

        def fake_member_model(seat: Any, model: str, *, max_retries: int) -> Any:
            return _Fake(model)

        monkeypatch.setattr(council_module, "member_model", fake_member_model)
        return calls

    @pytest.mark.anyio
    async def test_members_vote_concurrently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fakes(monkeypatch, {"slow_all": "ok"})
        # Every fake sleeps 0.1 s: patch behavior via slow fakes keyed by model.
        {seat.model: "slow" for seat in COUNCIL}

        class _SlowFake:
            def __init__(self, model: str) -> None:
                self.model = model

            async def ainvoke(self, messages: Any) -> Any:
                await asyncio.sleep(0.1)
                return ballot(["for", "unsure"])

        def fake_member_model(seat: Any, model: str, *, max_retries: int) -> Any:
            return _SlowFake(model)

        monkeypatch.setattr(council_module, "member_model", fake_member_model)
        started = time.monotonic()
        ballots = await convene(
            1,
            range(1, 8),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=5,
        )
        elapsed = time.monotonic() - started
        assert set(ballots) == set(range(1, 8))
        assert elapsed < 0.5

    @pytest.mark.anyio
    async def test_failed_members_are_dropped_while_quorum_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        behavior = {
            COUNCIL[2].model: "raise",
            COUNCIL[3].model: "slow",
            COUNCIL[4].model: "invalid",
            COUNCIL[5].model: "none",
        }
        self._fakes(monkeypatch, behavior)
        import agents.deep_forecaster.config as config

        monkeypatch.setattr(
            council_module,
            "LIMITS",
            __import__("dataclasses").replace(config.LIMITS, member_seconds=0.05),
        )
        with pytest.raises(LLMInvocationError) as exc:
            await convene(
                1,
                range(1, 8),
                lambda member: [],
                claims=2,
                quoted_by_claim=QUOTED_BY_CLAIM,
                quorum=5,
            )
        assert "Only 3 of 7" in str(exc.value) and "needs 5" in str(exc.value)

    @pytest.mark.anyio
    async def test_failed_members_are_absent_while_quorum_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        behavior = {
            COUNCIL[2].model: "raise",
            COUNCIL[5].model: "none",
        }
        self._fakes(monkeypatch, behavior)
        # Act
        ballots = await convene(
            1,
            range(1, 8),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=5,
        )
        # Assert
        assert set(ballots) == {1, 2, 4, 5, 7}

    @pytest.mark.anyio
    async def test_no_quorum_returns_whatever_voted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        behavior = {seat.model: "raise" for seat in COUNCIL}
        self._fakes(monkeypatch, behavior)
        ballots = await convene(
            2,
            range(1, 8),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=0,
        )
        assert ballots == {}

    @pytest.mark.anyio
    async def test_a_dropped_member_is_logged_with_its_models(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        caplog.set_level(logging.WARNING, logger=council_module.__name__)
        behavior = {COUNCIL[0].model: "raise"}
        self._fakes(monkeypatch, behavior)
        await convene(
            1,
            range(1, 3),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=1,
        )
        assert f"{COUNCIL[0].model}: RuntimeError" in caplog.text
        assert "dropped" in caplog.text

        await convene(
            2,
            range(1, 3),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=1,
        )
        assert "kept its round-1 vote" in caplog.text


class TestCast:
    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        behavior: dict[str, str],
        ballot_to_return: Ballot | None = None,
    ) -> dict[tuple[str, int], int]:
        """Fakes keyed by model id, recording `max_retries` per model."""
        calls: dict[tuple[str, int], int] = {}

        class _Fake:
            def __init__(self, model: str, retries: int) -> None:
                self.model = model
                self.retries = retries

            async def ainvoke(self, messages: Any) -> Any:
                calls[(self.model, self.retries)] = (
                    calls.get((self.model, self.retries), 0) + 1
                )
                action = behavior.get(self.model, "ok")
                if action == "raise":
                    raise openai.RateLimitError(
                        "rate limited",
                        response=httpx.Response(
                            429,
                            request=httpx.Request(
                                "POST", "https://openrouter.ai/api/v1/chat/completions"
                            ),
                        ),
                        body=None,
                    )
                if action == "timeout":
                    await asyncio.sleep(10)
                if action == "none":
                    return None
                if action == "invalid":
                    return ballot(["unsure"], evidence={1: [7]})
                return ballot_to_return or ballot(["for", "unsure"])

        def fake_member_model(seat: Any, model: str, *, max_retries: int) -> Any:
            return _Fake(model, max_retries)

        monkeypatch.setattr(council_module, "member_model", fake_member_model)
        return calls

    @pytest.mark.anyio
    @pytest.mark.parametrize("member", range(1, 8))
    async def test_every_seat_casts_one_attempt_with_the_client_s_retries(
        self,
        member: int,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        # Arrange
        caplog.set_level(logging.INFO, logger=council_module.__name__)
        seat = COUNCIL[member - 1]
        calls = self._patch(monkeypatch, {})
        # Act
        result, attempts = await _cast(
            1, member, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM
        )
        # Assert
        assert isinstance(result, Ballot)
        assert result.votes[0].claim == 1
        assert attempts == 1
        assert set(calls) == {(seat.model, DEFAULT_MAX_RETRIES)}
        assert "voted via" in caplog.text and seat.model in caplog.text

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("behavior", "attempts_expected"),
        [
            pytest.param("raise", 1, id="outage, not re-asked"),
            pytest.param("none", 2, id="no ballot, re-asked"),
            pytest.param("invalid", 2, id="broken rule, re-asked"),
        ],
    )
    async def test_a_failed_member_is_dropped(
        self,
        behavior: str,
        attempts_expected: int,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An outage is dropped on its first try; a broken answer is asked once
        more and dropped when its second answer breaks a rule too (Q1)."""
        import logging

        # Arrange
        caplog.set_level(logging.WARNING, logger=council_module.__name__)
        seat = COUNCIL[2]
        calls = self._patch(monkeypatch, {seat.model: behavior})
        # Act
        result, attempts = await _cast(
            1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM
        )
        # Assert
        assert isinstance(result, council_module.NoBallot)
        assert attempts == attempts_expected
        assert set(calls) == {(seat.model, DEFAULT_MAX_RETRIES)}
        assert f"{seat.model}: " in caplog.text and "dropped" in caplog.text

    @pytest.mark.anyio
    async def test_the_member_timeout_bounds_the_attempt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        # Arrange
        caplog.set_level(logging.WARNING, logger=council_module.__name__)
        seat = COUNCIL[2]
        self._patch(monkeypatch, {seat.model: "timeout"})
        small = dataclasses.replace(config.LIMITS, member_seconds=0.1)
        monkeypatch.setattr(council_module, "LIMITS", small)
        started = time.monotonic()
        # Act
        result, attempts = await _cast(
            1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM
        )
        elapsed = time.monotonic() - started
        # Assert
        assert result == council_module.NoBallot(
            council_module.MEMBER_TIME_LIMIT, fault="provider"
        )
        assert attempts == 1
        assert elapsed < 0.3
        assert "the member's time limit" in caplog.text


@pytest.mark.anyio
async def test_the_wall_cap_cancels_an_attempt_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    seat = COUNCIL[2]
    behavior = {seat.model: "timeout"}
    TestCast()._patch(monkeypatch, behavior)
    # Act
    task = asyncio.ensure_future(
        _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    # Assert
    with pytest.raises(asyncio.CancelledError):
        await task


class TestFinalBallots:
    def test_each_member_keeps_its_latest_or_first_ballot(self) -> None:
        first = {1: ballot(["for", "unsure"]), 2: ballot(["for", "unsure"])}
        second = {2: ballot(["against", "for"])}
        final = final_ballots(first, second)
        assert final[1] is first[1]
        assert final[2] is second[2]
        assert set(final) == {1, 2}


class TestMemberClient:
    def _recorded(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        recorded: list[dict[str, Any]] = []

        def fake_chat_openai(**kwargs: Any) -> Any:
            recorded.append(kwargs)
            return SimpleNamespace(**kwargs)

        monkeypatch.setattr(council_module, "ChatOpenAI", fake_chat_openai)
        return recorded

    def test_every_member_client_uses_openrouter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        recorded = self._recorded(monkeypatch)
        # Act
        for seat in COUNCIL:
            member_client(seat, seat.model)
        # Assert
        assert len(recorded) == len(COUNCIL)
        for seat, kwargs in zip(COUNCIL, recorded, strict=True):
            assert kwargs["model"] == seat.model
            assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
            assert kwargs["api_key"].get_secret_value() == "router-key"
            assert kwargs["disabled_params"] == {"parallel_tool_calls": None}
            assert kwargs["reasoning_effort"] == seat.reasoning_effort
            assert kwargs["timeout"] == 100.0
            assert kwargs["max_completion_tokens"] == 8_192
            assert kwargs["streaming"] is False
            assert kwargs["max_retries"] == 2

    def test_the_member_client_carries_the_max_retries_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
        recorded = self._recorded(monkeypatch)
        # Act
        member_client(COUNCIL[0], COUNCIL[0].model, max_retries=0)
        # Assert
        assert recorded[0]["max_retries"] == 0


def test_the_council_is_seven_paid_openrouter_seats_one_per_vendor() -> None:
    # Assert
    assert [(seat.model, seat.reasoning_effort) for seat in COUNCIL] == [
        ("openai/gpt-6-luna", "low"),
        ("google/gemini-3.5-flash-lite", "low"),
        ("anthropic/claude-haiku-5.5", None),
        ("z-ai/glm-5.3-flash", None),
        ("deepseek/deepseek-v4.1-flash", None),
        ("qwen/qwen3.8-flash", "none"),
        ("moonshotai/kimi-k2.5", None),
    ]
    vendors = [seat.model.split("/")[0] for seat in COUNCIL]
    assert len(vendors) == len(set(vendors))
    assert not any(seat.model.endswith(":free") for seat in COUNCIL)
    assert not any(hasattr(seat, "provider") for seat in COUNCIL)
