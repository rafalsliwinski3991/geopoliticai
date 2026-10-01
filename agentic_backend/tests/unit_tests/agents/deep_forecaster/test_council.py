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
from agents.deep_forecaster.state import Ballot, Stance, Vote
from models import LLMInvocationError
from unit_tests.agents.deep_forecaster.conftest import ballot

council_module: Any = importlib.import_module("agents.deep_forecaster.council")


SHOWN = frozenset({1, 3})


def _valid() -> Ballot:
    return ballot(["for", "unsure"], evidence={1: [1]})


class TestValidateBallot:
    def test_a_well_formed_ballot_counts(self) -> None:
        assert validate_ballot(_valid(), claims=2, shown=SHOWN) is None

    def test_an_unsure_vote_needs_no_evidence(self) -> None:
        ballot_ = ballot(["unsure", "unsure"], evidence={})
        assert validate_ballot(ballot_, claims=2, shown=SHOWN) is None

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
        assert validate_ballot(ballot_, claims=2, shown=SHOWN) == why

    def test_an_empty_reason(self) -> None:
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason="   ", evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert validate_ballot(ballot_, claims=2, shown=SHOWN) == "an empty reason"

    def test_a_reason_over_the_limit(self) -> None:
        long = "r" * 601
        ballot_ = Ballot(
            votes=[
                Vote(claim=1, stance="for", reason=long, evidence=[1]),
                Vote(claim=2, stance="unsure", reason="ok", evidence=[]),
            ]
        )
        assert (
            validate_ballot(ballot_, claims=2, shown=SHOWN)
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
        assert validate_ballot(ballot_, claims=2, shown=SHOWN) is None


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
            1, range(1, 8), lambda member: [], claims=2, shown=SHOWN, quorum=5
        )
        elapsed = time.monotonic() - started
        assert set(ballots) == set(range(1, 8))
        assert elapsed < 0.5

    @pytest.mark.anyio
    async def test_failed_members_are_dropped_while_quorum_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        behavior = {
            "nvidia/nemotron-3-ultra-550b-a55b:free": "raise",
            "nvidia/nemotron-3-ultra-550b-a55b": "raise",
            "qwen/qwen3.8-27b:free": "slow",
            "qwen/qwen3.8-27b": "slow",
            "thinkingmachines/inkling:free": "invalid",
            "thinkingmachines/inkling": "invalid",
            "dots-studio/dots-3-note-preview:free": "none",
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
                1, range(1, 8), lambda member: [], claims=2, shown=SHOWN, quorum=5
            )
        assert "Only 3 of 7" in str(exc.value) and "needs 5" in str(exc.value)

    @pytest.mark.anyio
    async def test_no_quorum_returns_whatever_voted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        behavior = {seat.model: "raise" for seat in COUNCIL}
        behavior.update({seat.fallback: "raise" for seat in COUNCIL if seat.fallback})
        self._fakes(monkeypatch, behavior)
        ballots = await convene(
            2, range(1, 8), lambda member: [], claims=2, shown=SHOWN, quorum=0
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
            1, range(1, 3), lambda member: [], claims=2, shown=SHOWN, quorum=1
        )
        assert "gpt-5-mini: RuntimeError" in caplog.text
        assert "dropped" in caplog.text

        await convene(
            2, range(1, 3), lambda member: [], claims=2, shown=SHOWN, quorum=1
        )
        assert "kept its round-1 vote" in caplog.text


class TestCastFallback:
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
    @pytest.mark.parametrize(
        "free_behavior",
        ["raise", "none", "invalid", "timeout"],
    )
    async def test_a_failed_free_model_asks_its_paid_fallback(
        self,
        free_behavior: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        caplog.set_level(logging.INFO, logger=council_module.__name__)
        seat = COUNCIL[2]
        free_model = seat.model
        fallback = str(seat.fallback)
        behavior = {free_model: free_behavior}
        calls = self._patch(monkeypatch, behavior)
        caplog.set_level(logging.INFO, logger=council_module.__name__)

        small = dataclasses.replace(
            config.LIMITS, free_attempt_seconds=0.05, member_seconds=1
        )
        monkeypatch.setattr(council_module, "LIMITS", small)
        # Act
        result = await _cast(1, 3, [], claims=2, shown=SHOWN)
        # Assert
        assert result is not None and result.votes[0].claim == 1
        assert calls[(fallback, 2)] == 1
        if free_behavior == "timeout":
            assert calls.get((free_model, 0)) == 1
        else:
            assert calls[(free_model, 0)] == 1
        assert "voted via" in caplog.text and fallback in caplog.text

    @pytest.mark.anyio
    @pytest.mark.anyio
    async def test_a_free_model_that_votes_never_calls_the_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._patch(monkeypatch, {})
        result = await _cast(1, 3, [], claims=2, shown=SHOWN)
        assert result is not None
        seat = COUNCIL[2]
        assert (str(seat.fallback), 2) not in calls
        assert (seat.model, 0) in calls

    @pytest.mark.anyio
    async def test_paid_seats_have_one_attempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        behavior = {"gpt-5-mini": "raise", "gemini-3.8-flash": "raise"}
        calls = self._patch(monkeypatch, behavior)
        first = await _cast(1, 1, [], claims=2, shown=SHOWN)
        second = await _cast(1, 2, [], claims=2, shown=SHOWN)
        assert first is None and second is None
        assert set(calls) == {("gpt-5-mini", 2), ("gemini-3.8-flash", 2)}

    @pytest.mark.anyio
    async def test_the_member_timeout_bounds_both_attempts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        caplog.set_level(logging.WARNING, logger=council_module.__name__)
        free = COUNCIL[2]
        assert free.fallback is not None
        behavior = {free.model: "timeout", free.fallback: "timeout"}
        self._patch(monkeypatch, behavior)

        small = dataclasses.replace(
            config.LIMITS, member_seconds=0.1, free_attempt_seconds=0.05
        )
        monkeypatch.setattr(council_module, "LIMITS", small)
        started = time.monotonic()
        result = await _cast(1, 3, [], claims=2, shown=SHOWN)
        elapsed = time.monotonic() - started
        assert result is None
        assert elapsed < 0.3
        assert "the member's time limit" in caplog.text


@pytest.mark.anyio
async def test_the_wall_cap_cancels_a_fallback_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    free = COUNCIL[2]
    assert free.fallback is not None
    behavior = {free.model: "timeout", free.fallback: "timeout"}
    TestCastFallback()._patch(monkeypatch, behavior)
    task = asyncio.ensure_future(_cast(1, 3, [], claims=2, shown=SHOWN))
    await asyncio.sleep(0.05)
    task.cancel()
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
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
        recorded = self._recorded(monkeypatch)
        member_client(COUNCIL[0], COUNCIL[0].model)
        member_client(COUNCIL[1], COUNCIL[1].model)
        free_seat = COUNCIL[2]
        member_client(free_seat, free_seat.model)
        assert free_seat.fallback is not None
        member_client(free_seat, free_seat.fallback)
        openai_client = recorded[0]
        gemini_client = recorded[1]
        free_client = recorded[2]
        fallback_client = recorded[3]
        assert "base_url" not in openai_client
        assert (
            gemini_client["base_url"]
            == "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        assert gemini_client["api_key"] == "gemini-key"
        assert free_client["base_url"] == "https://openrouter.ai/api/v1"
        assert free_client["api_key"] == "router-key"
        assert fallback_client["base_url"] == "https://openrouter.ai/api/v1"
        assert gemini_client["disabled_params"] == {"parallel_tool_calls": None}
        assert free_client["disabled_params"] == {"parallel_tool_calls": None}
        assert "disabled_params" not in openai_client
        for kwargs in recorded:
            assert kwargs["timeout"] == 100.0
            assert kwargs["max_completion_tokens"] == 8_192
            assert kwargs["streaming"] is False
        assert openai_client["max_retries"] == 2
        assert free_client["max_retries"] == 2
        member_client(COUNCIL[0], COUNCIL[0].model, max_retries=0)
        assert recorded[-1]["max_retries"] == 0


def test_every_free_seat_has_a_paid_fallback_from_no_seated_vendor() -> None:
    seated_vendors = {seat.model.split("/")[0] for seat in COUNCIL if "/" in seat.model}
    for seat in COUNCIL:
        if seat.provider == "openrouter":
            assert seat.model.endswith(":free")
            assert seat.fallback is not None and not seat.fallback.endswith(":free")
            vendor = seat.fallback.split("/")[0]
            assert vendor not in seated_vendors or vendor == seat.model.split("/")[0]
        else:
            assert seat.fallback is None
