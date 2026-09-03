import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agents.orchestrator.state import RouteDecision
from models import LLMInvocationError

node_module = importlib.import_module("agents.orchestrator.nodes.classify")


@pytest.mark.anyio
async def test_classify_returns_route_and_normalized_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            destination="geopolitical", standalone_query="  and   Poland?  "
        )

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    result = await node_module.classify({"messages": [HumanMessage("and Poland?")]})

    assert result == {
        "destination": "geopolitical",
        "standalone_query": "and Poland?",
    }
    assert received["schema"] is RouteDecision


@pytest.mark.anyio
async def test_classify_rejects_whitespace_only_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def decide(*args: Any, **kwargs: Any) -> RouteDecision:
        return RouteDecision(destination="other", standalone_query=" \t ")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    with pytest.raises(LLMInvocationError):
        await node_module.classify({"messages": [HumanMessage("hello")]})


@pytest.mark.anyio
async def test_classify_uses_last_history_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    await node_module.classify({"messages": messages})

    assert len(received) == 20
    assert received[0].content == "message 10"
