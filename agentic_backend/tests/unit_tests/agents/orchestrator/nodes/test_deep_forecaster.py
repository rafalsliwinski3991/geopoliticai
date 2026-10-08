"""Unit tests for `agents.orchestrator.nodes.deep_forecaster`."""

from __future__ import annotations

import types
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agents.orchestrator.state import OrchestratorState

node_module: Any = __import__(
    "agents.orchestrator.nodes.deep_forecaster", fromlist=["deep_forecaster"]
)

FORECAST_ANSWER = "Forecast answer [a](https://reuters.com/x)."


@pytest.mark.anyio
async def test_the_node_receives_the_query_and_writes_exactly_one_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    received: dict[str, Any] = {}
    events: list[dict[str, Any]] = []

    async def fake_forecast(query: str, store: Any = None) -> str:
        received["query"] = query
        received["store"] = store
        return FORECAST_ANSWER

    monkeypatch.setattr(node_module, "forecast", fake_forecast)
    state: OrchestratorState = {
        "messages": [],
        "standalone_query": "the rewritten query",
    }

    # Act
    result = await node_module.deep_forecaster(
        state, types.SimpleNamespace(store=None, stream_writer=events.append)
    )

    # Assert: the runtime's store reaches forecast() (review thread, #151).
    assert received["query"] == "the rewritten query"
    assert received["store"] is None
    assert events == [{"type": "notice", "text": FORECAST_ANSWER}]
    assert result == {"messages": [AIMessage(FORECAST_ANSWER)]}
