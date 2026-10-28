"""Unit tests for the reporter specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

from agents.orchestrator.tools.reporter import run_reporter
from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE
from shared.errors import LLMInvocationError
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

reporter_tool_module = importlib.import_module("agents.orchestrator.tools.reporter")


class _PausingReport:
    """Fake for `report` that pauses at the approval gate."""

    def __init__(self, outline_sections: list[str]) -> None:
        self._outline_sections = outline_sections

    async def __call__(self, transcript: str) -> dict[str, Any]:
        raise GraphInterrupt(
            [Interrupt(value={"outline": list(self._outline_sections)})]
        )


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

    async def fake_report(transcript: str) -> dict[str, Any]:
        return {"report": compiled_report}

    monkeypatch.setattr(reporter_tool_module, "report", fake_report)

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
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_rep_compile"
    assert message.content == "Report compiled (43 chars)."
    assert message.artifact == {"text": compiled_report}


@pytest.mark.anyio
async def test_run_reporter_propagates_the_pause_at_the_approval_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reporter subgraph that pauses must pause the orchestrator's turn too."""
    # Arrange
    outline_sections = ["1. Strategic Context", "2. Scenario Projections"]
    monkeypatch.setattr(
        reporter_tool_module, "report", _PausingReport(outline_sections)
    )
    emitted_events: list[dict[str, Any]] = []
    runtime = make_tool_runtime(
        state={
            "messages": [
                HumanMessage("What is the Baltic defense strategy?"),
                ToolMessage(
                    content="Briefing material",
                    tool_call_id="call_research_1",
                    artifact={
                        "text": "Verified source [1](https://example.com/baltic)."
                    },
                ),
            ],
            "expert_synthesis": ["Verified source with analysis."],
        },
        tool_call_id="call_rep_pause",
        writer=emitted_events.append,
    )

    # Act + Assert
    with pytest.raises(GraphInterrupt) as exc_info:
        await run_reporter.ainvoke({"topic": "Baltic defense", "runtime": runtime})
    assert [interrupt.value for interrupt in exc_info.value.args[0]] == [
        {"outline": outline_sections}
    ]
    assert emitted_events == []


@pytest.mark.anyio
async def test_run_reporter_emits_notice_when_report_is_cancelled_or_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the reporter subgraph returns no report (e.g. user cancelled or revision cap hit),
    the notice text must be emitted to stream_writer and saved as the ToolMessage artifact.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []

    async def fake_report(transcript: str) -> dict[str, Any]:
        return {"report": "", "notice": CANCELLED_NOTICE}

    monkeypatch.setattr(reporter_tool_module, "report", fake_report)

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
    assert update["messages"][0].artifact == {"text": CANCELLED_NOTICE}


@pytest.mark.anyio
async def test_run_reporter_hands_the_reporter_the_thread_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reporter writes from the thread, so the prior answer's artifact text must reach it."""
    # Arrange
    received: list[str] = []

    async def fake_report(transcript: str) -> dict[str, Any]:
        received.append(transcript)
        return {"report": "# Report"}

    monkeypatch.setattr(reporter_tool_module, "report", fake_report)
    runtime = make_tool_runtime(
        state={
            "messages": [
                HumanMessage("What is the Baltic posture?"),
                ToolMessage(
                    content="Briefing summary",
                    tool_call_id="call_prev",
                    artifact={"text": "Baltic briefing [1](https://example.com/b)."},
                ),
            ],
        },
    )

    # Act
    await run_reporter.ainvoke({"topic": "Baltic", "runtime": runtime})

    # Assert
    assert "Baltic briefing [1](https://example.com/b)." in received[0]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("graph_result", "expected_text"),
    [
        pytest.param(
            {"report": "", "notice": "Revision cap reached."},
            "Revision cap reached.",
            id="graph-notice-wins",
        ),
        pytest.param({"report": ""}, CANCELLED_NOTICE, id="cancelled-fallback"),
    ],
)
async def test_run_reporter_without_a_report_emits_the_graph_notice_or_the_cancelled_notice(
    monkeypatch: pytest.MonkeyPatch,
    graph_result: dict[str, Any],
    expected_text: str,
) -> None:
    """A run with no report shows the graph's own notice, and CANCELLED_NOTICE only without one."""
    # Arrange
    emitted_events: list[dict[str, Any]] = []

    async def fake_report(transcript: str) -> dict[str, Any]:
        return graph_result

    monkeypatch.setattr(reporter_tool_module, "report", fake_report)
    runtime = make_tool_runtime(
        state={"messages": [HumanMessage("Topic")], "expert_synthesis": ["Material."]},
        writer=emitted_events.append,
    )

    # Act
    command = await run_reporter.ainvoke({"topic": "Topic", "runtime": runtime})

    # Assert
    assert emitted_events == [{"type": "notice", "text": expected_text}]
    assert command.update["messages"][0].artifact == {"text": expected_text}


@pytest.mark.anyio
async def test_run_reporter_lets_a_pipeline_error_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed report run must reach the API's error frame, not become a tool result."""

    # Arrange
    async def failing_report(transcript: str) -> dict[str, Any]:
        raise LLMInvocationError("Model call failed.")

    monkeypatch.setattr(reporter_tool_module, "report", failing_report)
    runtime = make_tool_runtime(
        state={"messages": [HumanMessage("Topic")], "expert_synthesis": ["Material."]}
    )

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await run_reporter.ainvoke({"topic": "Topic", "runtime": runtime})
