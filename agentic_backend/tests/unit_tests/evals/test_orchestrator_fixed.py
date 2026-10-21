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


class RecordingClassifier:
    """Stands in for the `classify` node: records what it saw, returns one decision."""

    def __init__(self, decision: dict[str, Any]) -> None:
        self.decision = decision
        self.seen: list[list[AnyMessage]] = []

    async def __call__(self, state: dict[str, Any], writer: Any) -> dict[str, Any]:
        self.seen.append(list(state["messages"]))
        return self.decision


@pytest.mark.anyio
async def test_the_orchestrator_eval_runs_only_the_classifier() -> None:
    # Arrange
    classifier = RecordingClassifier(
        {"destination": "geopolitical", "standalone_query": "Who objected to 5%?"}
    )
    classify_module = importlib.import_module("agents.orchestrator.nodes.classify")

    # Act
    with patch.object(classify_module, "classify", classifier):
        output = await run_orchestrator_fixed({"messages": CONVERSATION})

    # Assert
    assert output == {
        "destination": "geopolitical",
        "standalone_query": "Who objected to 5%?",
    }
    assert len(classifier.seen) == 1
    assert [type(message) for message in classifier.seen[0]] == [
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert [message.content for message in classifier.seen[0]] == [
        "What did NATO agree?",
        "A 5% target.",
        "And who objected?",
    ]
