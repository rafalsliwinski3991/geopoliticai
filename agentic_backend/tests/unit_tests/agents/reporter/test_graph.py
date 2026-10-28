import importlib
from typing import Any, AsyncIterator

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agents.reporter import report
from agents.reporter.config import MAX_REVISION_ROUNDS
from agents.reporter.consts.messages import CANCELLED_NOTICE, REVISION_CAP_NOTICE
from agents.reporter.state import OutlineDraft, build_initial_reporter_state
from shared.errors import LLMInvocationError

graph_module = importlib.import_module("agents.reporter.graph")
outline_module = importlib.import_module("agents.reporter.nodes.outline")
write_module = importlib.import_module("agents.reporter.nodes.write")

TRANSCRIPT = "User: eastern flank?\n\nAssistant: Here it is [1](https://example.com/a)."


def _stub_outline_model(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[list[str]],
    sections_per_call: list[list[str]],
) -> None:
    """Stub the outline model, serving one section list per call.

    The last entry repeats once exhausted, so the revision-cap test does not
    need an entry per call.
    """

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> OutlineDraft:
        index = min(len(calls), len(sections_per_call) - 1)
        sections = sections_per_call[index]
        calls.append(list(sections))
        return OutlineDraft(sections=list(sections), notice="")

    monkeypatch.setattr(outline_module, "ainvoke_structured", decide)


def _stub_report_writer(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], text: str = "The report."
) -> None:
    async def stream(
        prompt: str,
        human_prompt: str,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        calls.append(human_prompt)
        yield text

    monkeypatch.setattr(write_module, "astream_text", stream)


def _compiled() -> Any:
    return graph_module.build_graph(checkpointer=InMemorySaver())


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


@pytest.mark.anyio
async def test_first_run_pauses_at_the_gate_with_the_drafted_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First", "Second"]])
    compiled = _compiled()

    # Act
    await compiled.ainvoke(
        build_initial_reporter_state(TRANSCRIPT), config=_config("pause-1")
    )
    state = compiled.get_state(config=_config("pause-1"))

    # Assert
    assert state.next == ("gate",)
    assert state.interrupts[0].value["outline"] == ["First", "Second"]


@pytest.mark.anyio
async def test_a_revise_resume_redraws_and_pauses_again_with_the_new_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    _stub_outline_model(
        monkeypatch, outline_calls, [["Old outline"], ["New one", "New two"]]
    )
    compiled = _compiled()
    config = _config("revise-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(
        Command(resume={"action": "revise", "instruction": "add Poland"}), config=config
    )
    state = compiled.get_state(config=config)

    # Assert
    assert state.next == ("gate",)
    assert state.interrupts[0].value["outline"] == ["New one", "New two"]
    assert len(outline_calls) == 2


@pytest.mark.anyio
async def test_an_approve_resume_writes_the_report_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, [], [["First", "Second"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("approve-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(Command(resume={"action": "approve"}), config=config)
    state = compiled.get_state(config=config)

    # Assert
    assert state.next == ()
    assert state.values["report"] == "The report."
    assert write_calls


@pytest.mark.anyio
async def test_a_cancel_resume_ends_without_a_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cancel-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(Command(resume={"action": "cancel"}), config=config)
    state = compiled.get_state(config=config)

    # Assert
    assert state.next == ()
    assert state.values["report"] == ""
    assert state.values["notice"] == CANCELLED_NOTICE
    assert write_calls == []


@pytest.mark.anyio
async def test_two_revisions_and_an_approval_cost_three_outline_calls_and_one_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cost-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(
        Command(resume={"action": "revise", "instruction": "first change"}),
        config=config,
    )
    await compiled.ainvoke(
        Command(resume={"action": "revise", "instruction": "second change"}),
        config=config,
    )
    await compiled.ainvoke(Command(resume={"action": "approve"}), config=config)

    # Assert
    assert len(outline_calls) == 3
    assert len(write_calls) == 1


@pytest.mark.anyio
async def test_an_empty_transcript_ends_immediately_without_pausing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("empty-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(""), config=config)
    state = compiled.get_state(config=config)

    # Assert
    assert state.next == ()
    assert state.values["outline"] == []
    assert state.interrupts == ()
    assert outline_calls == []
    assert write_calls == []


@pytest.mark.anyio
async def test_max_revision_rounds_plus_one_revisions_end_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cap-1")

    # Act
    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    for round_number in range(MAX_REVISION_ROUNDS + 1):
        await compiled.ainvoke(
            Command(
                resume={
                    "action": "revise",
                    "instruction": f"change {round_number + 1}",
                }
            ),
            config=config,
        )
    state = compiled.get_state(config=config)

    # Assert
    # Asserting next == () is the point: an outline node that returned its
    # sections unchanged at the cap would leave the thread paused forever.
    assert state.next == ()
    assert state.values["report"] == ""
    assert state.values["notice"] == REVISION_CAP_NOTICE
    assert len(outline_calls) == MAX_REVISION_ROUNDS + 1
    assert write_calls == []


class RecordingGraph:
    """A compiled-graph stand-in: records each input and returns or raises what it was given."""

    def __init__(
        self, result: dict[str, Any] | None = None, error: Exception | None = None
    ):
        self.inputs: list[Any] = []
        self._result = result
        self._error = error

    async def ainvoke(self, graph_input: Any) -> dict[str, Any]:
        self.inputs.append(graph_input)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


@pytest.mark.anyio
async def test_report_returns_what_the_graph_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's tool reads `report` and `notice` from the graph's own
    state, so the wrapper must hand that state back untouched."""
    # Arrange
    final_state = {"report": "# Report", "notice": ""}
    fake_graph = RecordingGraph(result=final_state)
    monkeypatch.setattr(graph_module, "graph", fake_graph)

    # Act
    result = await report(TRANSCRIPT)

    # Assert
    assert fake_graph.inputs == [
        {
            "transcript": TRANSCRIPT,
            "outline": [],
            "notice": "",
            "instruction": "",
            "revisions": 0,
            "report": "",
        }
    ]
    assert result == final_state


@pytest.mark.anyio
async def test_report_lets_a_pipeline_error_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A graph failure must reach the API's error frame, not turn into an empty report."""
    # Arrange
    monkeypatch.setattr(
        graph_module, "graph", RecordingGraph(error=LLMInvocationError("model down"))
    )

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="model down"):
        await report(TRANSCRIPT)
