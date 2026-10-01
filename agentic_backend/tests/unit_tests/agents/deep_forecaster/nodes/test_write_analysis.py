"""Unit tests for `agents.deep_forecaster.nodes.write_analysis`."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from agents.deep_forecaster.consts.progress import WRITE_LABEL
from agents.deep_forecaster.state import (
    Analysis,
    ClaimDiscussion,
    ClaimTally,
)
from unit_tests.agents.deep_forecaster.conftest import ballot, runtime, state

write_analysis_module: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.write_analysis"
)


@pytest.mark.anyio
async def test_the_writer_reads_verdicts_votes_and_sources(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    returned = Analysis(
        overview="Overview.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha."),
            ClaimDiscussion(claim=2, discussion="Beta."),
        ],
    )
    recorded: dict[str, Any] = {}

    async def fake_ainvoke(
        system: str,
        messages: Any,
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> Any:
        recorded["system"] = system
        recorded["messages"] = messages
        recorded["settings"] = settings
        return returned

    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", fake_ainvoke)
    first = {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: one for member, one in first.items() if member != 4}
    forecast_state: Any = state(round_1=first, round_2=second)
    forecast_state["tally"] = [
        ClaimTally(
            claim=1, verdict="ACCEPTED", votes_for=7, against=0, unsure=0, voting=7
        ),
        ClaimTally(
            claim=2, verdict="UNRESOLVED", votes_for=0, against=0, unsure=7, voting=7
        ),
    ]
    # Act
    out = await write_analysis_module.write_analysis(forecast_state, runtime(events))
    # Assert
    assert out["analysis"] is returned
    human = str(recorded["messages"][0].content)
    assert "Claim 1: ACCEPTED (7 for, 0 against, 0 unsure, of 7 voting)" in human
    assert "Member 4 (did not answer round 2; its round-1 vote):" in human
    assert "Reason 1." in human and "Reason 2." in human
    assert "https://carnegieendowment.org/a" in human
    assert "https://reuters.com/b" in human
    assert "Today is 30 September 2026." in recorded["system"]
    assert recorded["settings"] is write_analysis_module.WRITE_LLM_SETTINGS
    assert events == [
        {"type": "progress", "node": "deep_forecaster", "label": WRITE_LABEL}
    ]
