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

import agents.deep_forecaster.config as config
from agents.deep_forecaster.config import COUNCIL
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
from unit_tests.agents.deep_forecaster.conftest import ballot

council_module: Any = importlib.import_module("agents.deep_forecaster.council")


# What claim 1 and claim 2 quote, per claim: tests give every vote the
# evidence the claims themselves carry (review thread, #142).
QUOTED_BY_CLAIM = {1: frozenset({1, 3}), 2: frozenset({1, 3})}


def _valid() -> Ballot:
    return ballot(["for", "unsure"], evidence={1: [1]})


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
            (ballot(["for"]), "not exactly one vote per claim"),
            (ballot(["for", "against", "unsure"]), "not exactly one vote per claim"),
            (
                ballot(["for", "unsure"], evidence={1: []}),
                "a 'for' vote without evidence",
            ),
            (
                ballot(["for", "unsure"], evidence={1: [2]}),
                "evidence it was not given",
            ),
            (
                ballot(["for", "unsure"], evidence={1: [9]}),
                "evidence it was not given",
            ),
            (
                ballot(["for", "unsure"], evidence={1: [1, 3, 2, 3, 2, 1]}),
                "more evidence than the limit",
            ),
        ],
    )
    def test_refusals(self, ballot_: Ballot, why: str) -> None:
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
            == "an empty reason"
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
            == "a reason over the length limit"
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
            "nvidia/nemotron-3-ultra-550b-a55b": "raise",
            "qwen/qwen3.8-27b": "slow",
            "poolside/laguna-s-2.1": "invalid",
            "deepseek/deepseek-v4-flash": "none",
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
    async def test_a_failed_member_is_absent_while_quorum_holds(
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
        behavior = {"gpt-5-mini": "raise"}
        self._fakes(monkeypatch, behavior)
        await convene(
            1,
            range(1, 3),
            lambda member: [],
            claims=2,
            quoted_by_claim=QUOTED_BY_CLAIM,
            quorum=1,
        )
        assert "gpt-5-mini: RuntimeError" in caplog.text
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
        result = await _cast(1, member, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
        # Assert
        assert result is not None and result.votes[0].claim == 1
        assert set(calls) == {(seat.model, DEFAULT_MAX_RETRIES)}
        assert "voted via" in caplog.text and seat.model in caplog.text

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "behavior",
        ["raise", "none", "invalid"],
    )
    async def test_a_failed_attempt_is_dropped_without_a_second_try(
        self,
        behavior: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        # Arrange
        caplog.set_level(logging.WARNING, logger=council_module.__name__)
        seat = COUNCIL[2]
        calls = self._patch(monkeypatch, {seat.model: behavior})
        # Act
        result = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
        # Assert
        assert result is None
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
        result = await _cast(1, 3, [], claims=2, quoted_by_claim=QUOTED_BY_CLAIM)
        elapsed = time.monotonic() - started
        # Assert
        assert result is None
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

    def test_member_clients_by_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
        recorded = self._recorded(monkeypatch)
        # Act
        member_client(COUNCIL[0], COUNCIL[0].model)
        member_client(COUNCIL[1], COUNCIL[1].model)
        router_seat = COUNCIL[2]
        member_client(router_seat, router_seat.model)
        # Assert
        openai_client = recorded[0]
        gemini_client = recorded[1]
        router_client = recorded[2]
        assert "base_url" not in openai_client
        assert (
            gemini_client["base_url"]
            == "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        assert gemini_client["api_key"] == "gemini-key"
        assert router_client["base_url"] == "https://openrouter.ai/api/v1"
        assert router_client["api_key"] == "router-key"
        assert gemini_client["disabled_params"] == {"parallel_tool_calls": None}
        assert router_client["disabled_params"] == {"parallel_tool_calls": None}
        assert "disabled_params" not in openai_client
        for kwargs in recorded:
            assert kwargs["timeout"] == 100.0
            assert kwargs["max_completion_tokens"] == 8_192
            assert kwargs["streaming"] is False
        assert openai_client["max_retries"] == 2
        assert router_client["max_retries"] == 2

    def test_the_member_client_carries_the_max_retries_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
        recorded = self._recorded(monkeypatch)
        # Act
        member_client(COUNCIL[0], COUNCIL[0].model, max_retries=0)
        # Assert
        assert recorded[0]["max_retries"] == 0


def test_the_openrouter_roster_is_one_paid_seat_per_vendor() -> None:
    # Assert
    vendors = [seat.model.split("/")[0] for seat in COUNCIL if "/" in seat.model]
    assert len(vendors) == len(set(vendors))
    for seat in COUNCIL:
        if seat.provider == "openrouter":
            assert not seat.model.endswith(":free")
