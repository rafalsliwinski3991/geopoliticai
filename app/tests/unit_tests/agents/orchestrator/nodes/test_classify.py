import importlib
from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage

from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.orchestrator.state import Destination, RouteDecision
from models import LLMInvocationError

node_module = importlib.import_module("agents.orchestrator.nodes.classify")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("destination", "expected_events"),
    [
        ("geopolitical", [SEARCH_PROGRESS]),
        ("other", []),
        ("report", []),
    ],
)
async def test_classify_returns_route_and_normalized_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    destination: str,
    expected_events: list[dict[str, Any]],
) -> None:
    # Arrange
    received: dict[str, Any] = {}

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: type[RouteDecision],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> RouteDecision:
        received.update(prompt=prompt, messages=messages, schema=schema)
        return RouteDecision(
            destination=cast(Destination, destination),
            standalone_query="  and   Poland?  ",
        )

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    events: list[Any] = []
    # Act
    result = await node_module.classify(
        {"messages": [HumanMessage("and Poland?")]}, writer=events.append
    )

    # Assert
    assert result == {
        "destination": destination,
        "standalone_query": "and Poland?",
    }
    assert received["schema"] is RouteDecision
    assert events == expected_events


@pytest.mark.anyio
async def test_classify_rejects_whitespace_only_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        return RouteDecision(destination="other", standalone_query=" \t ")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    events: list[Any] = []
    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await node_module.classify(
            {"messages": [HumanMessage("hello")]}, writer=events.append
        )


@pytest.mark.anyio
async def test_classify_uses_last_history_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    received: list[Any] = []

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: type[RouteDecision],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> RouteDecision:
        received.extend(messages)
        return RouteDecision(destination="other", standalone_query="question")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    messages = [HumanMessage(f"message {index}") for index in range(30)]
    events: list[Any] = []
    # Act
    await node_module.classify({"messages": messages}, writer=events.append)

    # Assert
    assert len(received) == 20
    assert received[0].content == "message 10"
