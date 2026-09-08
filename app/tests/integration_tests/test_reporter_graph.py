import importlib
from typing import Any, AsyncIterator

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agents.reporter.config import MAX_REVISION_ROUNDS
from agents.reporter.consts.messages import CANCELLED_NOTICE, REVISION_CAP_NOTICE
from agents.reporter.state import OutlineDraft, build_initial_reporter_state

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
    outline_calls: list[list[str]] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First", "Second"]])
    compiled = _compiled()

    await compiled.ainvoke(
        build_initial_reporter_state(TRANSCRIPT), config=_config("pause-1")
    )
    state = compiled.get_state(config=_config("pause-1"))

    assert state.next == ("gate",)
    assert state.interrupts[0].value["outline"] == ["First", "Second"]


@pytest.mark.anyio
async def test_a_revise_resume_redraws_and_pauses_again_with_the_new_outline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    _stub_outline_model(
        monkeypatch, outline_calls, [["Old outline"], ["New one", "New two"]]
    )
    compiled = _compiled()
    config = _config("revise-1")

    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(
        Command(resume={"action": "revise", "instruction": "add Poland"}), config=config
    )
    state = compiled.get_state(config=config)

    assert state.next == ("gate",)
    assert state.interrupts[0].value["outline"] == ["New one", "New two"]
    assert len(outline_calls) == 2


@pytest.mark.anyio
async def test_an_approve_resume_writes_the_report_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, [], [["First", "Second"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("approve-1")

    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(Command(resume={"action": "approve"}), config=config)
    state = compiled.get_state(config=config)

    assert state.next == ()
    assert state.values["report"] == "The report."
    assert write_calls


@pytest.mark.anyio
async def test_a_cancel_resume_ends_without_a_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cancel-1")

    await compiled.ainvoke(build_initial_reporter_state(TRANSCRIPT), config=config)
    await compiled.ainvoke(Command(resume={"action": "cancel"}), config=config)
    state = compiled.get_state(config=config)

    assert state.next == ()
    assert state.values["report"] == ""
    assert state.values["notice"] == CANCELLED_NOTICE
    assert write_calls == []


@pytest.mark.anyio
async def test_two_revisions_and_an_approval_cost_three_outline_calls_and_one_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cost-1")

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

    assert len(outline_calls) == 3
    assert len(write_calls) == 1


@pytest.mark.anyio
async def test_an_empty_transcript_ends_immediately_without_pausing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("empty-1")

    await compiled.ainvoke(build_initial_reporter_state(""), config=config)
    state = compiled.get_state(config=config)

    assert state.next == ()
    assert state.values["outline"] == []
    assert state.interrupts == ()
    assert outline_calls == []
    assert write_calls == []


@pytest.mark.anyio
async def test_max_revision_rounds_plus_one_revisions_end_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline_calls: list[list[str]] = []
    write_calls: list[str] = []
    _stub_outline_model(monkeypatch, outline_calls, [["First"]])
    _stub_report_writer(monkeypatch, write_calls)
    compiled = _compiled()
    config = _config("cap-1")

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

    # Asserting next == () is the point: an outline node that returned its
    # sections unchanged at the cap would leave the thread paused forever.
    assert state.next == ()
    assert state.values["report"] == ""
    assert state.values["notice"] == REVISION_CAP_NOTICE
    assert len(outline_calls) == MAX_REVISION_ROUNDS + 1
    assert write_calls == []
