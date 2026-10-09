"""Unit tests for `agents.deep_forecaster.nodes.tally`."""

import importlib
from typing import Any

import pytest

from unit_tests.agents.deep_forecaster.conftest import ballot, state

tally_module: Any = importlib.import_module("agents.deep_forecaster.nodes.tally")


tally_node: Any = tally_module


@pytest.mark.anyio
async def test_the_tally_counts_each_members_latest_ballot(
    events: list[dict[str, Any]],
) -> None:
    # Arrange
    first = {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: ballot(["against", "for"]) for member in range(1, 7)}
    forecast_state = state(round_1=first, round_2=second)
    # Act
    out = await tally_node.tally(forecast_state)
    tally = out["tally"]
    # Member 7 kept its round-1 vote; every count is of 7 voting.
    # Assert
    assert all(t.voting == 7 for t in tally)
    assert tally[0].votes_for == 1 and tally[0].against == 6
