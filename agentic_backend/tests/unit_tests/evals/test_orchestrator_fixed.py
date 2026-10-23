"""Unit tests for `evals.orchestrator_fixed`."""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from evals.orchestrator_fixed import run_orchestrator_fixed

CONVERSATION = [
    {"role": "user", "content": "What did NATO agree?"},
    {"role": "assistant", "content": "A 5% target."},
    {"role": "user", "content": "And who objected?"},
]


class RecordingSupervisor:
    """Stands in for the `supervisor` node: records what it saw, returns one result."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.seen: list[list[AnyMessage]] = []

    async def __call__(self, state: dict[str, Any], writer: Any) -> dict[str, Any]:
        self.seen.append(list(state["messages"]))
        return self.result


@pytest.mark.anyio
async def test_the_orchestrator_eval_extracts_destination_and_standalone_query_from_supervisor_tool_call() -> (
    None
):
    """When the supervisor emits a specialist tool call, destination and query must be extracted for evaluation."""
    # Arrange
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "run_expert",
                "args": {"query": "Who objected to 5%?"},
                "id": "call_123",
                "type": "tool_call",
            }
        ],
    )
    supervisor = RecordingSupervisor(
        {"destination": "geopolitical", "messages": [ai_msg]}
    )
    supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")

    # Act
    with patch.object(supervisor_module, "supervisor", supervisor):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": "geopolitical",
        "standalone_query": "Who objected to 5%?",
    }
    assert len(supervisor.seen) == 1
    assert [type(message) for message in supervisor.seen[0]] == [
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert [message.content for message in supervisor.seen[0]] == [
        "What did NATO agree?",
        "A 5% target.",
        "And who objected?",
    ]


@pytest.mark.anyio
async def test_the_orchestrator_eval_handles_direct_chat_turn_without_tool_calls() -> (
    None
):
    """When the supervisor answers directly without calling a tool, destination defaults to other and query is empty."""
    # Arrange
    ai_msg = AIMessage(content="Hello! How can I help you today?")
    supervisor = RecordingSupervisor({"destination": "other", "messages": [ai_msg]})
    supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")

    # Act
    with patch.object(supervisor_module, "supervisor", supervisor):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": "other",
        "standalone_query": "",
    }
    assert len(supervisor.seen) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arg_key", "arg_value"),
    [
        ("question", "What was agreed at the summit?"),
        ("topic", "European energy security"),
    ],
    ids=["question-field", "topic-field"],
)
async def test_the_orchestrator_eval_extracts_standalone_query_from_alternate_tool_arg_keys(
    arg_key: str, arg_value: str
) -> None:
    """Specialist tools may receive the rewritten query under query, question, or topic args."""
    # Arrange
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "run_deep_expert",
                "args": {arg_key: arg_value},
                "id": "call_456",
                "type": "tool_call",
            }
        ],
    )
    supervisor = RecordingSupervisor({"destination": "deep", "messages": [ai_msg]})
    supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")

    # Act
    with patch.object(supervisor_module, "supervisor", supervisor):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": "deep",
        "standalone_query": arg_value,
    }
    assert len(supervisor.seen) == 1
