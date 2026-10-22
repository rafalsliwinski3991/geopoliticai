"""Unit tests for `evals.e2e_deep_forecaster`.

The live eval never runs here: every test feeds `build_graph` a fake whose
`astream` is a scripted generator, and `require_env` is patched away where
`run_e2e_deep_forecaster` imports it, so no Brave search, page read, or model
call happens.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

import agents.deep_forecaster.config as config_module
from agents.deep_forecaster.consts.editorial import VOTE_LIST_HEADING
from agents.deep_forecaster.council import QuorumError
from agents.deep_forecaster.models import Ballot, Claim, EvidenceRef, Stance, Vote
from agents.deep_forecaster.state import ClaimTally
from evals.e2e_deep_forecaster import (
    forecast_output,
    run_e2e_deep_forecaster,
)
from models import (
    Source,
)

QUERY = "Forecast if Russia will attack Poland?"
WALL_SECONDS = 0.05
# Expanding on the gap script: the run starts its clock at 8; the steps' ends
# fall at 10 (write_analysis), 12 (verify), 17 (the rewrite) and 18 (the call).
MONOTONICS = [8.0, 10.0, 12.0, 17.0, 18.0]


def _ballot(stances: list[Stance]) -> Ballot:
    return Ballot(
        votes=[
            Vote(
                claim=number,
                stance=stance,
                reason="Because of the read pages.",
                evidence=[1] if stance != "unsure" else [],
            )
            for number, stance in enumerate(stances, start=1)
        ]
    )


def _state() -> dict[str, Any]:
    """The finished forecast the deleted recorded eval's test carried, plus the pages read."""
    claims = [
        Claim(
            statement="Claim one happens by 2027.",
            deadline=date(2027, 12, 31),
            evidence=[EvidenceRef(source=1, paragraph=1)],
        ),
        Claim(
            statement="Claim two happens by 2028.",
            deadline=date(2028, 6, 30),
            evidence=[],
        ),
    ]
    first = {member: _ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: _ballot(["for", "against"]) for member in range(1, 6)}
    sources = [
        Source(title="First", url="https://news.example/one", text="first page text"),
        Source(title="Second", url="https://news.example/two", text="second page text"),
    ]
    answer = (
        "Overview: trouble is brewing [one](https://news.example/one).\n"
        f"{VOTE_LIST_HEADING}\n"
        "- one member [two](https://news.example/two)"
    )
    return {
        "answer": answer,
        "claims": claims,
        "sources": sources,
        "ballots_round_1": first,
        "ballots_round_2": second,
        "tally": [
            ClaimTally(
                claim=1, verdict="ACCEPTED", votes_for=5, against=1, unsure=0, voting=6
            ),
            ClaimTally(
                claim=2, verdict="REJECTED", votes_for=0, against=6, unsure=0, voting=6
            ),
        ],
    }


@pytest.mark.anyio
async def test_a_failed_forecast_becomes_a_report_row() -> None:
    # Arrange
    fake_graph = _GraphThatFailsOnStream(
        updates=[{"research": {"sources": []}}],
        error=QuorumError("round 1 ended below quorum", outside=False),
    )
    with (
        patch("agents.deep_forecaster.graph.build_graph", return_value=fake_graph),
        patch("config.require_env", return_value=None),
    ):
        # Act
        output = await run_e2e_deep_forecaster({"query": QUERY})
    # Assert
    assert output["finished"] is False
    assert output["side"] == "ours"
    assert output["cause"].startswith("QuorumError:")
    assert "research" in output["step_seconds"]


@pytest.mark.anyio
async def test_a_forecast_past_the_wall_is_our_failure() -> None:
    # Arrange
    fake_graph = _GraphThatNeverEnds()
    short_limits = replace(config_module.LIMITS, wall_seconds=WALL_SECONDS)
    with (
        patch("agents.deep_forecaster.graph.build_graph", return_value=fake_graph),
        patch.object(config_module, "LIMITS", short_limits),
        patch("config.require_env", return_value=None),
    ):
        # Act
        output = await run_e2e_deep_forecaster({"query": QUERY})
    # Assert
    assert output["finished"] is False
    assert output["side"] == "ours"
    assert "wall" in output["cause"]


def test_forecast_output_reports_verdicts_passages_and_cited_pages() -> None:
    # Arrange
    state = _state()
    # Act
    output = forecast_output(state, {})
    # Assert
    assert output["verdicts"] == ["Claim 1: ACCEPTED", "Claim 2: REJECTED"]
    assert output["claims"][0] == (
        "Claim 1: Claim one happens by 2027. (deadline: 2027-12-31)"
    )
    assert '- Source 1: "first page text"' in output["passages"]
    assert output["source_urls"] == [
        "https://news.example/one",
        "https://news.example/two",
    ]
    assert output["analysis"].startswith("Overview: trouble is brewing")
    assert VOTE_LIST_HEADING not in output["analysis"]
    assert output["cited_sources"] == [
        {
            "title": "First",
            "url": "https://news.example/one",
            "text": "first page text",
        }
    ]
    assert output["members_voting"] == 7


class _GraphThatNeverEnds:
    """A built graph whose `astream` never ends, as a hung step's stream would not."""

    def astream(self, *_: Any, **__: Any) -> AsyncIterator[dict[str, Any]]:
        async def stream() -> AsyncIterator[dict[str, Any]]:
            await asyncio.sleep(3_600)
            yield {}

        return stream()


class _GraphThatYields:
    """A built graph whose `astream` yields the scripted updates, then stops."""

    def __init__(self, updates: list[dict[str, Any]]) -> None:
        self.updates = updates

    def astream(self, *_: Any, **__: Any) -> AsyncIterator[dict[str, Any]]:
        async def stream() -> AsyncIterator[dict[str, Any]]:
            for update in self.updates:
                yield update

        return stream()


class _GraphThatFailsOnStream(_GraphThatYields):
    """A built graph whose `astream` yields, then raises one scripted error."""

    def __init__(
        self, updates: list[dict[str, Any]], error: BaseException | None
    ) -> None:
        super().__init__(updates)
        self.error = error

    def astream(self, *_: Any, **__: Any) -> AsyncIterator[dict[str, Any]]:
        async def stream() -> AsyncIterator[dict[str, Any]]:
            async for update in super(_GraphThatFailsOnStream, self).astream():
                yield update
            if self.error is not None:
                raise self.error

        return stream()


@pytest.mark.anyio
async def test_step_times_add_the_writers_rewrite() -> None:
    # Arrange: the cap is passed through (`run_under_time_limits` waits with
    # `asyncio.wait`, whose own loop-clock ticks would shift the gaps); the
    # wall seam itself is `test_a_forecast_past_the_wall_is_our_failure`'s rule.
    async def immediate(coro: Any, _wall_seconds: float) -> tuple[Any, bool]:
        return await coro, False

    finished = _state()
    updates: list[dict[str, Any]] = [
        {"write_analysis": {"answer": "first pass"}},
        {"verify": {}},
        {"write_analysis": finished},
    ]
    fake_graph = _GraphThatYields(updates=updates)
    clock = list(MONOTONICS)
    with (
        patch("agents.deep_forecaster.graph.build_graph", return_value=fake_graph),
        patch("config.require_env", return_value=None),
        # Extra ticks (asyncio housekeeping) hold the last value, so an
        # unexpected call cannot shift the gaps; the 5 scripted ticks give
        # started=8 s and step ends at 10, 12 and 17 s, total at 18 s.
        patch("agents.deep_forecaster.time_limits.run_under_time_limits", immediate),
        patch(
            "evals.e2e_deep_forecaster.time.monotonic",
            side_effect=lambda: clock.pop(0) if len(clock) > 1 else clock[0],
        ),
    ):
        # Act
        output = await run_e2e_deep_forecaster({"query": QUERY})
    # Assert: one `write_analysis` entry holding both gaps (2 s + 5 s, by hand).
    assert output["step_seconds"] == {"write_analysis": 7.0, "verify": 2.0}
