"""Unit tests for `agents.deep_forecaster.nodes.write_analysis`."""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from agents.deep_forecaster.consts.progress import REWRITE_LABEL, WRITE_LABEL
from agents.deep_forecaster.council import final_ballots
from agents.deep_forecaster.models import Analysis, ClaimDiscussion
from agents.deep_forecaster.prompts import RETRY_INSTRUCTIONS
from agents.deep_forecaster.state import ClaimTally
from unit_tests.agents.deep_forecaster.conftest import (
    MISSING_CLAIM_DEFECT,
    ballot,
    runtime,
    state,
)

write_analysis_module: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.write_analysis"
)


def a_written_analysis() -> Analysis:
    """The writer's dummy structured reply, one section per claim."""
    return Analysis(
        overview="Overview.",
        claims=[
            ClaimDiscussion(claim=1, discussion="Alpha."),
            ClaimDiscussion(claim=2, discussion="Beta."),
        ],
    )


def a_tallied_state() -> Any:
    """A state past the tally: seven ballots, member 4 silent in round 2, verdicts counted."""
    first = {member: ballot(["for", "unsure"]) for member in range(1, 8)}
    second = {member: one for member, one in first.items() if member != 4}
    forecast_state: Any = state(round_1=first, round_2=second)
    forecast_state["final_ballots"] = final_ballots(first, second)
    forecast_state["tally"] = [
        ClaimTally(
            claim=1, verdict="ACCEPTED", votes_for=7, against=0, unsure=0, voting=7
        ),
        ClaimTally(
            claim=2, verdict="UNRESOLVED", votes_for=0, against=0, unsure=7, voting=7
        ),
    ]
    return forecast_state


def briefing_writer(returned: Analysis) -> tuple[dict[str, Any], Any]:
    """A recording fake for `ainvoke_structured`, with the record it fills."""
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

    return recorded, fake_ainvoke


@pytest.mark.anyio
async def test_the_writer_reads_verdicts_votes_and_sources(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    # Arrange
    recorded, a_fake = briefing_writer(a_written_analysis())
    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", a_fake)
    forecast_state: Any = a_tallied_state()
    # Act
    out = await write_analysis_module.write_analysis(forecast_state, runtime(events))
    # Assert
    assert out["analysis"] == a_written_analysis()
    human = str(recorded["messages"][0].content)
    assert "Claim 1: ACCEPTED (7 for, 0 against, 0 unsure, of 7 voting)" in human
    assert "Member 4 (did not answer round 2; its round-1 vote):" in human
    assert "Reason 1." in human and "Reason 2." in human
    # The writer never sees a URL: it cites by number, and verify links.
    assert "https://" not in human
    assert "A article" in human and "Alpha one." in human and "Alpha three." in human
    assert "B article" in human and "Beta one." in human and "Beta three." in human
    assert "Today is 30 September 2026." in recorded["system"]
    assert recorded["settings"] is write_analysis_module.WRITE_LLM_SETTINGS
    assert events == [
        {"type": "progress", "node": "deep_forecaster", "label": WRITE_LABEL}
    ]


@pytest.mark.anyio
async def test_the_writer_reads_the_final_ballots_the_tally_stored(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """The writer's votes are the ballots `tally` stored, never a rebuild from the rounds."""
    # Arrange
    recorded, a_fake = briefing_writer(a_written_analysis())
    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", a_fake)
    forecast_state: Any = a_tallied_state()
    forecast_state["final_ballots"] = {
        member: ballot(["against", "unsure"]) for member in range(1, 8)
    }
    # Act
    await write_analysis_module.write_analysis(forecast_state, runtime(events))
    # Assert
    human = str(recorded["messages"][0].content)
    assert "Member 1:\nClaim 1: against — Reason 1. (Sources 1)" in human


@pytest.mark.anyio
async def test_a_url_in_the_question_never_reaches_the_writer(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """The writer sees no URL anywhere in its brief — the question included:
    a URL there would be copied into the analysis and cost the one rewrite."""

    # Arrange
    recorded, a_fake = briefing_writer(a_written_analysis())
    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", a_fake)
    forecast_state: Any = a_tallied_state()
    forecast_state["question"] = "Will it happen? See https://evil.example/q"

    # Act
    await write_analysis_module.write_analysis(forecast_state, runtime(events))

    # Assert
    human = str(recorded["messages"][0].content)
    assert "Question: Will it happen? See (link removed)" in human
    assert "https://" not in human


@pytest.mark.anyio
async def test_the_retry_brief_carries_the_defect(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """On the one rewrite, the writer is re-briefed with verify's defect named."""
    # Arrange
    recorded, a_fake = briefing_writer(a_written_analysis())
    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", a_fake)
    forecast_state: Any = a_tallied_state()
    forecast_state["feedback"] = MISSING_CLAIM_DEFECT
    # Act
    await write_analysis_module.write_analysis(forecast_state, runtime(events))
    # Assert
    human = str(recorded["messages"][0].content)
    assert human.endswith(RETRY_INSTRUCTIONS.format(defect=MISSING_CLAIM_DEFECT))
    assert events == [
        {"type": "progress", "node": "deep_forecaster", "label": REWRITE_LABEL}
    ]


@pytest.mark.anyio
async def test_a_first_brief_has_no_retry_text(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    """The first write is briefed without verify's retry text and at the write label."""
    # Arrange
    recorded, a_fake = briefing_writer(a_written_analysis())
    monkeypatch.setattr(write_analysis_module, "ainvoke_structured", a_fake)
    # Act
    await write_analysis_module.write_analysis(a_tallied_state(), runtime(events))
    # Assert
    human = str(recorded["messages"][0].content)
    assert "rejected" not in human
    assert events == [
        {"type": "progress", "node": "deep_forecaster", "label": WRITE_LABEL}
    ]
