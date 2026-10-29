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
async def test_the_orchestrator_eval_extracts_destination_and_standalone_query_from_the_orchestrator_tool_call() -> (
    None
):
    """When the orchestrator emits a specialist tool call, destination and query must be extracted for evaluation."""
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
        "search_query": "",
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
async def test_the_orchestrator_eval_extracts_search_query_from_run_expert() -> None:
    """A Polish question reaches `run_expert` with an English search query, which the eval grades."""
    # Arrange
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "run_expert",
                "args": {
                    "query": "A Polska?",
                    "search_query": "What did Poland decide?",
                },
                "id": "call_789",
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
    assert output["search_query"] == "What did Poland decide?"


@pytest.mark.anyio
async def test_the_orchestrator_eval_handles_direct_chat_turn_without_tool_calls() -> (
    None
):
    """When the orchestrator answers directly without calling a tool, destination defaults to other and query is empty."""
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
        "search_query": "",
    }
    assert len(supervisor.seen) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "destination", "arg_key", "arg_value"),
    [
        (
            "run_deep_forecaster",
            "forecast",
            "question",
            "What was agreed at the summit?",
        ),
        ("run_reporter", "report", "topic", "European energy security"),
    ],
    ids=["forecaster-question", "reporter-topic"],
)
async def test_the_orchestrator_eval_extracts_standalone_query_from_alternate_tool_arg_keys(
    tool_name: str, destination: str, arg_key: str, arg_value: str
) -> None:
    """Specialist tools may receive the rewritten query under query, question, or topic args."""
    # Arrange
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": {arg_key: arg_value},
                "id": "call_456",
                "type": "tool_call",
            }
        ],
    )
    supervisor = RecordingSupervisor({"destination": destination, "messages": [ai_msg]})
    supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")

    # Act
    with patch.object(supervisor_module, "supervisor", supervisor):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": destination,
        "standalone_query": arg_value,
        "search_query": "",
    }
    assert len(supervisor.seen) == 1


@pytest.mark.anyio
async def test_the_orchestrator_eval_reports_other_when_the_orchestrator_names_no_destination() -> (
    None
):
    """A chat answer returns no tool call and, from a bare fake, no destination."""
    # Arrange
    supervisor = RecordingSupervisor({"messages": [AIMessage("Hello!")]})
    supervisor_module = importlib.import_module("agents.orchestrator.nodes.supervisor")

    # Act
    with patch.object(supervisor_module, "supervisor", supervisor):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": "other",
        "standalone_query": "",
        "search_query": "",
    }
