"""Unit tests for `agents.deep_forecaster.nodes.council` (the rounds)."""

import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agents.deep_forecaster.consts.progress import ROUND_LABEL
from unit_tests.agents.deep_forecaster.conftest import ballot, state

council_nodes_module: Any = importlib.import_module(
    "agents.deep_forecaster.nodes.council"
)
council_nodes: Any = council_nodes_module


def _runtime(events: list[dict[str, Any]]) -> Any:
    from types import SimpleNamespace

    from agents.deep_forecaster.state import ForecastRun
    from unit_tests.agents.deep_forecaster.conftest import TODAY

    return SimpleNamespace(
        context=ForecastRun(today=TODAY), stream_writer=events.append
    )


class _RecordedConvene:
    """Replaces `convene` with a recorder."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        round_number: int,
        members: Any,
        messages_for: Any,
        *,
        claims: int,
        shown: Any,
        quorum: int,
    ) -> dict[int, Any]:
        self.calls.append(
            {
                "round": round_number,
                "members": list(members),
                "messages": {member: messages_for(member) for member in members},
                "claims": claims,
                "shown": shown,
                "quorum": quorum,
            }
        )
        if round_number == 1:
            return {member: ballot(["for", "unsure"]) for member in members}
        return {}


@pytest.mark.anyio
async def test_round_1_convenes_every_member_with_a_quorum(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    recorded = _RecordedConvene()
    monkeypatch.setattr(council_nodes, "convene", recorded)
    forecast_state = state()
    await council_nodes.council_round_1(forecast_state, _runtime(events))
    call = recorded.calls[0]
    assert call["round"] == 1
    assert call["members"] == list(range(1, 8))
    assert call["quorum"] == 5
    assert call["shown"] == frozenset({1, 2})
    system = call["messages"][1][0]
    assert isinstance(system, SystemMessage) and "30 September 2026" in str(
        system.content
    )


@pytest.mark.anyio
async def test_members_read_the_passages_not_the_sources(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    recorded = _RecordedConvene()
    monkeypatch.setattr(council_nodes, "convene", recorded)
    await council_nodes.council_round_1(state(), _runtime(events))
    human = next(
        message
        for message in recorded.calls[0]["messages"][1]
        if isinstance(message, HumanMessage)
    )
    text = str(human.content)
    assert "Alpha one." in text
    assert "Beta two." in text
    assert "Alpha three." in text
    assert "Alpha two." not in text
    assert "Beta one." not in text
    assert "Beta three." not in text


@pytest.mark.anyio
async def test_round_2_convenes_only_round_1_voters_without_a_quorum(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    recorded = _RecordedConvene()
    monkeypatch.setattr(council_nodes, "convene", recorded)
    forecast_state = state(round_2={1: ballot(["against", "for"])})
    await council_nodes.council_round_2(forecast_state, _runtime(events))
    call = recorded.calls[0]
    assert call["round"] == 2
    assert call["members"] == list(range(1, 8))
    assert call["quorum"] == 0
    for member, messages in call["messages"].items():
        human = next(m for m in messages if isinstance(m, HumanMessage))
        assert str(human.content).endswith(
            council_nodes.round_one_view(member, forecast_state["ballots_round_1"])[
                -len("Reason 2.") :
            ]
        )


@pytest.mark.anyio
async def test_each_round_emits_its_own_label(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]]
) -> None:
    recorded = _RecordedConvene()
    monkeypatch.setattr(council_nodes, "convene", recorded)
    forecast_state = state()
    await council_nodes.council_round_1(forecast_state, _runtime(events))
    assert events[-1] == {
        "type": "progress",
        "node": "deep_forecaster",
        "label": ROUND_LABEL.format(round=1),
    }
    await council_nodes.council_round_2(forecast_state, _runtime(events))
    assert events[-1] == {
        "type": "progress",
        "node": "deep_forecaster",
        "label": ROUND_LABEL.format(round=2),
    }
