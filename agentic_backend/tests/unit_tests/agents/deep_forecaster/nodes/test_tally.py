"""Unit tests for `agents.deep_forecaster.nodes.tally`."""

import importlib
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from unit_tests.agents.deep_forecaster.conftest import ballot, state

tally_module: Any = importlib.import_module("agents.deep_forecaster.nodes.tally")


tally_node: Any = tally_module


def _span_by_name(captured: InMemorySpanExporter, name: str) -> ReadableSpan:
    matches = [
        span
        for span in captured.get_finished_spans()
        if span.name == name and span.attributes is not None
    ]
    assert len(matches) == 1, f"expected exactly one {name} span, got {len(matches)}"
    return matches[0]


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


@pytest.mark.anyio
async def test_the_tally_span_records_verdicts_and_changed_votes(
    captured_spans: InMemorySpanExporter,
) -> None:
    """The tally's decisions are on a `council_tally` span, so a Phoenix trace
    alone explains a run's verdicts and how far Delphi's second round moved the
    votes (brainstorm 2026Sep30 F4, span rule)."""
    # Arrange: every member for on claim 1 and unsure on claim 2 in round 1;
    # members 1-6 revise claim 2 to against in round 2, member 7 does not sit.
    first = {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: ballot(["for", "against"]) for member in range(1, 7)}
    forecast_state = state(round_1=first, round_2=second)
    # Act
    await tally_node.tally(forecast_state)
    # Assert
    span = _span_by_name(captured_spans, "council_tally")
    attributes = span.attributes
    assert attributes is not None
    assert attributes["tally.claims"] == 2
    assert attributes["tally.voting"] == 7
    assert attributes["tally.accepted"] == 1
    assert attributes["tally.rejected"] == 1
    assert attributes["tally.unresolved"] == 0
    assert attributes["tally.carried_votes"] == 1
    assert attributes["tally.changed_votes"] == 6
    assert attributes["tally.unanimous_claims"] == 1
