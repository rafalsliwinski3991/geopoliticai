import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

node_module = importlib.import_module("agents.orchestrator.nodes.expert")


@pytest.mark.anyio
async def test_expert_invokes_child_with_only_rewritten_pipeline_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[dict[str, Any]] = []

    class FakeExpertGraph:
        async def ainvoke(self, state: dict[str, Any]) -> dict[str, str]:
            received.append(state)
            return {"answer": "grounded answer"}

    monkeypatch.setattr(node_module, "expert_graph", FakeExpertGraph())
    result = await node_module.expert(
        {
            "messages": [HumanMessage("raw user turn")],
            "destination": "geopolitical",
            "standalone_query": "rewritten user turn",
        }
    )

    assert received == [{"query": "rewritten user turn", "sources": [], "answer": ""}]
    assert result == {"messages": [AIMessage("grounded answer")]}
