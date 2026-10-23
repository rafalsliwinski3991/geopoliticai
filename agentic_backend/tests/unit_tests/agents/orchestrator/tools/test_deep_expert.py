"""Unit tests for the deep expert specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from agents.orchestrator.tools.deep_expert import run_deep_expert
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

deep_expert_tool_module = importlib.import_module(
    "agents.orchestrator.tools.deep_expert"
)


@pytest.mark.anyio
async def test_run_deep_expert_parses_markdown_citations_and_updates_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep expert research returns an unstructured answer with markdown links; the tool
    must parse these into structured retrieved sources, append to synthesis, and emit a notice.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    research_calls: list[tuple[str, Any]] = []
    deep_answer = (
        "Comprehensive analysis of deterrence. "
        "See [IISS Military Balance](https://iiss.org/mb) and "
        "[SIPRI Database](https://sipri.org/db)."
    )

    async def fake_research(query: str, writer: Any) -> str:
        research_calls.append((query, writer))
        return deep_answer

    monkeypatch.setattr(deep_expert_tool_module, "research", fake_research)

    initial_state = {
        "messages": [],
        "retrieved_sources": [
            {"title": "Existing", "url": "https://iiss.org/mb"},
        ],
        "expert_synthesis": ["Prior synthesis."],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_deep_456",
        writer=emitted_events.append,
    )

    # Act
    command = await run_deep_expert.ainvoke(
        {"query": "Baltic deterrence", "runtime": runtime}
    )

    # Assert
    assert len(research_calls) == 1
    assert research_calls[0][0] == "Baltic deterrence"
    assert emitted_events == [{"type": "notice", "text": deep_answer}]

    update = command.update
    assert update["retrieved_sources"] == [
        {"title": "Existing", "url": "https://iiss.org/mb"},
        {"title": "SIPRI Database", "url": "https://sipri.org/db"},
    ]
    assert update["expert_synthesis"] == [
        "Prior synthesis.",
        deep_answer,
    ]
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_deep_456"
    assert message.content == "Deep research on 'Baltic deterrence' synthesized."
    assert message.artifact == {"text": deep_answer}


@pytest.mark.anyio
async def test_run_deep_expert_handles_answer_without_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When deep research generates an answer without markdown links, the tool
    appends synthesis without error and leaves retrieved_sources unaffected.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    plain_answer = "Analysis without any citations."

    async def fake_research(query: str, writer: Any) -> str:
        return plain_answer

    monkeypatch.setattr(deep_expert_tool_module, "research", fake_research)

    runtime = make_tool_runtime(
        state={"messages": []},
        tool_call_id="call_plain",
        writer=emitted_events.append,
    )

    # Act
    command = await run_deep_expert.ainvoke(
        {"query": "Uncited topic", "runtime": runtime}
    )

    # Assert
    update = command.update
    assert update["retrieved_sources"] == []
    assert update["expert_synthesis"] == [plain_answer]
    assert update["messages"][0].artifact == {"text": plain_answer}


@pytest.mark.anyio
async def test_run_deep_expert_extracts_citation_urls_containing_parentheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Citation URLs containing parentheses must be extracted in full without premature truncation.

    Wikipedia and treaty links commonly include parentheses such as '(1992)'; truncating them breaks source links.
    """
    # Arrange
    target_url = "https://en.wikipedia.org/wiki/Treaty_on_Open_Skies_(1992)"
    deep_answer = (
        f"The treaty details are available at [Treaty on Open Skies]({target_url})."
    )

    async def fake_research(query: str, writer: Any) -> str:
        return deep_answer

    monkeypatch.setattr(deep_expert_tool_module, "research", fake_research)

    runtime = make_tool_runtime(
        state={"messages": []},
        tool_call_id="call_parens",
        writer=lambda event: None,
    )

    # Act
    command = await run_deep_expert.ainvoke({"query": "Open Skies", "runtime": runtime})

    # Assert
    update = command.update
    assert update["retrieved_sources"] == [
        {"title": "Treaty on Open Skies", "url": target_url}
    ]
