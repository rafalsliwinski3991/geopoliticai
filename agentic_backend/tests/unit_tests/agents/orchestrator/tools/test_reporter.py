"""Unit tests for the reporter specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from agents.orchestrator.tools.reporter import run_reporter
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

reporter_tool_module = importlib.import_module("agents.orchestrator.tools.reporter")


@pytest.mark.anyio
async def test_run_reporter_refuses_when_workspace_has_no_researched_material() -> None:
    """When the thread and workspace contain no researched material, the reporter tool
    must refuse immediately without calling the subgraph, emitting NO_MATERIAL_NOTICE.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    initial_state = {
        "messages": [HumanMessage("Write a report on defense spending.")],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_rep_refuse",
        writer=emitted_events.append,
    )

    # Act
    command = await run_reporter.ainvoke(
        {"topic": "defense spending", "runtime": runtime}
    )

    # Assert
    assert emitted_events == [{"type": "notice", "text": NO_MATERIAL_NOTICE}]
    update = command.update
    assert update["report_draft"] == NO_MATERIAL_NOTICE
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_rep_refuse"
    assert message.content == NO_MATERIAL_NOTICE
    assert message.artifact == {"text": NO_MATERIAL_NOTICE}


@pytest.mark.anyio
async def test_run_reporter_compiles_report_when_workspace_has_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the workspace holds researched material, run_reporter builds the transcript,
    invokes the reporter subgraph, and stores the compiled report.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    compiled_report = "# Defense Report\n\nFull structured analysis."

    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        return {"report": compiled_report}

    monkeypatch.setattr(reporter_tool_module.reporter_graph, "ainvoke", fake_ainvoke)

    initial_state = {
        "messages": [
            HumanMessage("What is the defense posture?"),
            ToolMessage(
                content="Briefing summary",
                tool_call_id="call_prev",
                artifact={
                    "text": "Verified research with citations [1](https://example.com)."
                },
            ),
        ],
        "expert_synthesis": ["Verified research with citations."],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_rep_compile",
        writer=emitted_events.append,
    )

    # Act
    command = await run_reporter.ainvoke(
        {"topic": "defense posture", "runtime": runtime}
    )

    # Assert
    assert (
        emitted_events == []
    )  # On successful report compilation, report is not emitted as notice
    update = command.update
    assert update["report_draft"] == compiled_report
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_rep_compile"
    assert message.content == f"Report compiled ({len(compiled_report)} chars)."
    assert message.artifact == {"text": compiled_report}


@pytest.mark.anyio
async def test_run_reporter_emits_notice_when_report_is_cancelled_or_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the reporter subgraph returns no report (e.g. user cancelled or revision cap hit),
    the notice text must be emitted to stream_writer and saved as report_draft.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []

    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        return {"report": "", "notice": CANCELLED_NOTICE}

    monkeypatch.setattr(reporter_tool_module.reporter_graph, "ainvoke", fake_ainvoke)

    initial_state = {
        "messages": [HumanMessage("Topic")],
        "expert_synthesis": ["Some research material exists."],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_rep_cancel",
        writer=emitted_events.append,
    )

    # Act
    command = await run_reporter.ainvoke({"topic": "Topic", "runtime": runtime})

    # Assert
    assert emitted_events == [{"type": "notice", "text": CANCELLED_NOTICE}]
    update = command.update
    assert update["report_draft"] == CANCELLED_NOTICE
    assert update["messages"][0].artifact == {"text": CANCELLED_NOTICE}
