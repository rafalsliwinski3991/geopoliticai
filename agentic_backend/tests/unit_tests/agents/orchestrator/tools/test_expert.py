"""Unit tests for the expert specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from agents.orchestrator.consts.progress import SEARCH_PROGRESS
from agents.orchestrator.tools.expert import run_expert
from models import Source
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

expert_tool_module = importlib.import_module("agents.orchestrator.tools.expert")


@pytest.mark.anyio
async def test_run_expert_updates_sources_synthesis_and_returns_tool_message_with_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When expert research finishes, verified sources must be added to the shared workspace,
    the answer appended to expert synthesis, and a ToolMessage returned containing the full answer in its artifact.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    invoked_inputs: list[dict[str, Any]] = []

    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        invoked_inputs.append(input_state)
        return {
            "answer": "Verified NATO briefing [1](https://nato.int).",
            "sources": [
                Source(title="NATO Flank", url="https://nato.int/flank", text="Text 1"),
                Source(
                    title="Old Source", url="https://example.com/initial", text="Text 2"
                ),
            ],
        }

    monkeypatch.setattr(expert_tool_module.expert_graph, "ainvoke", fake_ainvoke)

    initial_state = {
        "messages": [],
        "retrieved_sources": [
            {"title": "Old Source", "url": "https://example.com/initial"}
        ],
        "expert_synthesis": ["Initial overview."],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_expert_123",
        writer=emitted_events.append,
    )

    # Act
    command = await run_expert.ainvoke(
        {"query": "NATO flank update", "runtime": runtime}
    )

    # Assert
    assert emitted_events == [SEARCH_PROGRESS]
    assert len(invoked_inputs) == 1
    assert invoked_inputs[0]["query"] == "NATO flank update"

    update = command.update
    assert update["retrieved_sources"] == [
        {"title": "Old Source", "url": "https://example.com/initial"},
        {"title": "NATO Flank", "url": "https://nato.int/flank"},
    ]
    assert update["expert_synthesis"] == [
        "Initial overview.",
        "Verified NATO briefing [1](https://nato.int).",
    ]
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_expert_123"
    assert (
        message.content
        == "Synthesized verified research on 'NATO flank update' from 2 sources."
    )
    assert message.artifact == {"text": "Verified NATO briefing [1](https://nato.int)."}


@pytest.mark.anyio
async def test_run_expert_handles_empty_initial_workspace_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the workspace starts with no prior sources or synthesis, run_expert
    initializes them cleanly without raising KeyError or NoneType errors.
    """

    # Arrange
    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        return {
            "answer": "Fresh answer.",
            "sources": [
                Source(title="Source One", url="https://example.com/1", text="Text 1")
            ],
        }

    monkeypatch.setattr(expert_tool_module.expert_graph, "ainvoke", fake_ainvoke)

    runtime = make_tool_runtime(state={"messages": []}, tool_call_id="call_fresh")

    # Act
    command = await run_expert.ainvoke({"query": "Fresh topic", "runtime": runtime})

    # Assert
    update = command.update
    assert update["retrieved_sources"] == [
        {"title": "Source One", "url": "https://example.com/1"}
    ]
    assert update["expert_synthesis"] == ["Fresh answer."]
    assert update["messages"][0].artifact == {"text": "Fresh answer."}
