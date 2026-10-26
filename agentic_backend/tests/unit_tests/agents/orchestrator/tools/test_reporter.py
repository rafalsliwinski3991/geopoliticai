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
from models import LLMInvocationError
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

reporter_tool_module = importlib.import_module("agents.orchestrator.tools.reporter")


class _ScriptedReporterGraph:
    """Scripted fake for reporter_graph across an interrupt-and-resume lifecycle."""

    def __init__(
        self,
        compiled_report: str,
        outline_sections: list[str],
    ) -> None:
        self.outline_calls: list[dict[str, Any]] = []
        self._compiled_report = compiled_report
        self._outline_sections = outline_sections
        self._call_count = 0

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        self._call_count += 1
        if self._call_count == 1:
            self.outline_calls.append(state)
            raise GraphInterrupt(
                [Interrupt(value={"outline": list(self._outline_sections)})]
            )
        if self._call_count == 2:
            return {"report": self._compiled_report}
        raise AssertionError(
            f"Unexpected extra call to reporter_graph.ainvoke: #{self._call_count}"
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
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_rep_compile"
    assert message.content == "Report compiled (43 chars)."
    assert message.artifact == {"text": compiled_report}


@pytest.mark.anyio
async def test_run_reporter_propagates_the_pause_and_returns_the_report_on_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the reporter subgraph pauses at the approval gate, run_reporter propagates
    the pause via GraphInterrupt and returns the compiled report on the next call.
    """
    # Arrange
    outline_sections = ["1. Strategic Context", "2. Scenario Projections"]
    compiled_report = "# Strategic Analysis\n\nDetailed breakdown of scenario risks."
    fake_graph = _ScriptedReporterGraph(
        compiled_report=compiled_report,
        outline_sections=outline_sections,
    )
    monkeypatch.setattr(reporter_tool_module, "reporter_graph", fake_graph)

    emitted_events: list[dict[str, Any]] = []
    initial_state = {
        "messages": [
            HumanMessage("What is the Baltic defense strategy?"),
            ToolMessage(
                content="Briefing material",
                tool_call_id="call_research_1",
                artifact={"text": "Verified source [1](https://example.com/baltic)."},
            ),
        ],
        "expert_synthesis": ["Verified source with analysis."],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_rep_pause_resume",
        writer=emitted_events.append,
    )

    # Act
    with pytest.raises(GraphInterrupt) as exc_info:
        await run_reporter.ainvoke({"topic": "Baltic defense", "runtime": runtime})
    command = await run_reporter.ainvoke(
        {"topic": "Baltic defense", "runtime": runtime}
    )

    # Assert
    interrupts = exc_info.value.args[0]
    assert [interrupt.value for interrupt in interrupts] == [
        {"outline": outline_sections}
    ]
    assert emitted_events == []
    update = command.update
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_rep_pause_resume"
    assert message.content == "Report compiled (59 chars)."
    assert message.artifact == {"text": compiled_report}


@pytest.mark.anyio
async def test_run_reporter_emits_notice_when_report_is_cancelled_or_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the reporter subgraph returns no report (e.g. user cancelled or revision cap hit),
    the notice text must be emitted to stream_writer and saved as the ToolMessage artifact.
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
    assert update["messages"][0].artifact == {"text": CANCELLED_NOTICE}


@pytest.mark.anyio
async def test_run_reporter_hands_the_reporter_the_thread_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reporter writes from the thread, so the prior answer's artifact text must reach it."""
    # Arrange
    received: list[dict[str, Any]] = []

    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        received.append(input_state)
        return {"report": "# Report"}

    monkeypatch.setattr(reporter_tool_module.reporter_graph, "ainvoke", fake_ainvoke)
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
    assert "Baltic briefing [1](https://example.com/b)." in received[0]["transcript"]


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

    async def fake_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        return graph_result

    monkeypatch.setattr(reporter_tool_module.reporter_graph, "ainvoke", fake_ainvoke)
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
    async def failing_ainvoke(input_state: dict[str, Any]) -> dict[str, Any]:
        raise LLMInvocationError("Model call failed.")

    monkeypatch.setattr(reporter_tool_module.reporter_graph, "ainvoke", failing_ainvoke)
    runtime = make_tool_runtime(
        state={"messages": [HumanMessage("Topic")], "expert_synthesis": ["Material."]}
    )

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await run_reporter.ainvoke({"topic": "Topic", "runtime": runtime})
