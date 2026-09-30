"""Unit tests for `agents.orchestrator.nodes.deep_expert`."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agents.orchestrator.state import OrchestratorState

node_module: Any = importlib.import_module("agents.orchestrator.nodes.deep_expert")

DEEP_ANSWER = "Deep answer [a](https://reuters.com/x)."


@pytest.mark.anyio
async def test_the_node_receives_the_query_and_writes_exactly_one_notice() -> None:
    # Arrange
    received: dict[str, Any] = {}
    events: list[dict[str, Any]] = []

    async def fake_research(query: str, writer: Any) -> str:
        received["query"] = query
        received["writer"] = writer
        return DEEP_ANSWER

    node_module.research = fake_research
    try:
        state: OrchestratorState = {
            "messages": [],
            "standalone_query": "the rewritten query",
        }

        # Act
        result = await node_module.deep_expert(state, events.append)
    finally:
        node_module.research = _restore()

    # Assert
    assert received["query"] == "the rewritten query"
    assert received["writer"] is not None
    assert events == [{"type": "notice", "text": DEEP_ANSWER}]
    assert result == {"messages": [AIMessage(DEEP_ANSWER)]}


def _restore() -> Any:
    async def research(query: str, writer: Any) -> str:
        raise AssertionError("research must be patched in tests")

    return research
