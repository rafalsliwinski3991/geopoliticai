"""Unit tests for the deep expert specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from agents.orchestrator.tools.deep_expert import run_deep_expert
from models import LLMInvocationError
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

deep_expert_tool_module = importlib.import_module(
    "agents.orchestrator.tools.deep_expert"
)


@pytest.mark.anyio
async def test_run_deep_expert_appends_synthesis_and_emits_the_answer_as_a_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deep answer reaches the browser once, as a notice, and joins expert synthesis."""
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    research_calls: list[tuple[str, Any]] = []
    deep_answer = "Comprehensive analysis of deterrence [IISS](https://iiss.org/mb)."

    async def fake_research(query: str, writer: Any) -> str:
        research_calls.append((query, writer))
        return deep_answer

    monkeypatch.setattr(deep_expert_tool_module, "research", fake_research)
    runtime = make_tool_runtime(
        state={"messages": [], "expert_synthesis": ["Prior synthesis."]},
        tool_call_id="call_deep_456",
        writer=emitted_events.append,
    )

    # Act
    command = await run_deep_expert.ainvoke(
        {"query": "Baltic deterrence", "runtime": runtime}
    )

    # Assert
    assert [call[0] for call in research_calls] == ["Baltic deterrence"]
    assert emitted_events == [{"type": "notice", "text": deep_answer}]
    update = command.update
    assert update["expert_synthesis"] == ["Prior synthesis.", deep_answer]
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_deep_456"
    assert message.content == "Deep research on 'Baltic deterrence' synthesized."
    assert message.artifact == {"text": deep_answer}


@pytest.mark.anyio
async def test_run_deep_expert_starts_the_synthesis_list_when_the_thread_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def fake_research(query: str, writer: Any) -> str:
        return "First deep answer."

    monkeypatch.setattr(deep_expert_tool_module, "research", fake_research)
    runtime = make_tool_runtime(state={"messages": []})

    # Act
    command = await run_deep_expert.ainvoke({"query": "Any topic", "runtime": runtime})

    # Assert
    assert command.update["expert_synthesis"] == ["First deep answer."]


@pytest.mark.anyio
async def test_run_deep_expert_lets_a_pipeline_error_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed deep run must reach the API's error frame, not become a tool result."""

    # Arrange
    async def failing_research(query: str, writer: Any) -> str:
        raise LLMInvocationError("Model call failed.")

    monkeypatch.setattr(deep_expert_tool_module, "research", failing_research)
    runtime = make_tool_runtime(state={"messages": []})

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await run_deep_expert.ainvoke({"query": "Any topic", "runtime": runtime})
