import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

from agents.reporter.config import MAX_REVISION_ROUNDS
from agents.reporter.consts.messages import NO_MATERIAL_NOTICE, REVISION_CAP_NOTICE
from agents.reporter.consts.progress import OUTLINE_PROGRESS
from agents.reporter.state import OutlineDraft

node_module = importlib.import_module("agents.reporter.nodes.outline")

TRANSCRIPT = "User: eastern flank?\n\nAssistant: Here it is [1](https://example.com/a)."


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "transcript": TRANSCRIPT,
        "outline": [],
        "notice": "",
        "instruction": "",
        "revisions": 0,
        "report": "",
    }
    state.update(overrides)
    return state


def _forbid_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*args: Any, **kwargs: Any) -> OutlineDraft:
        raise AssertionError("outline must not call the model on this path")

    monkeypatch.setattr(node_module, "ainvoke_structured", forbidden)


@pytest.mark.anyio
async def test_empty_transcript_refuses_without_a_model_call_or_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_model_call(monkeypatch)
    events: list[Any] = []

    result = await node_module.outline(_state(transcript="   "), writer=events.append)

    assert result == {
        "outline": [],
        "notice": NO_MATERIAL_NOTICE,
        "instruction": "",
    }
    assert events == []


@pytest.mark.anyio
async def test_spent_revision_budget_ends_with_empty_outline_and_no_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_model_call(monkeypatch)
    events: list[Any] = []

    result = await node_module.outline(
        _state(revisions=MAX_REVISION_ROUNDS + 1), writer=events.append
    )

    # The empty outline is what routes the run to END; returning the sections
    # unchanged here would leave the thread paused forever.
    assert result["outline"] == []
    assert result["notice"] == REVISION_CAP_NOTICE
    assert events == []


@pytest.mark.anyio
async def test_model_path_emits_progress_once_before_the_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    received: dict[str, Any] = {}

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> OutlineDraft:
        received["messages"] = messages
        received["schema"] = schema
        received["events_at_call"] = len(events)
        return OutlineDraft(sections=["First", "Second"], notice="")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)

    result = await node_module.outline(_state(), writer=events.append)

    assert events == [OUTLINE_PROGRESS]
    assert received["events_at_call"] == 1
    assert received["schema"] is OutlineDraft
    assert result["outline"] == ["First", "Second"]


@pytest.mark.anyio
async def test_sections_are_whitespace_normalized_and_blank_sections_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def decide(*args: Any, **kwargs: Any) -> OutlineDraft:
        return OutlineDraft(
            sections=["  Spread   out  ", " \t ", "Also fine"], notice=""
        )

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    events: list[Any] = []

    result = await node_module.outline(_state(), writer=events.append)

    assert result["outline"] == ["Spread out", "Also fine"]


@pytest.mark.anyio
async def test_an_empty_redraft_on_a_revision_keeps_the_previous_outline_and_surfaces_the_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = ["Keep me"]

    async def decide(*args: Any, **kwargs: Any) -> OutlineDraft:
        return OutlineDraft(sections=[], notice="  Not in the  transcript yet.  ")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    events: list[Any] = []

    result = await node_module.outline(
        _state(outline=previous, revisions=1, instruction="add Poland"),
        writer=events.append,
    )

    assert result["outline"] == ["Keep me"]
    assert result["notice"] == "Not in the transcript yet."


@pytest.mark.anyio
async def test_every_return_path_clears_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty_draft(*args: Any, **kwargs: Any) -> OutlineDraft:
        return OutlineDraft(sections=[], notice="refused")

    async def full_draft(*args: Any, **kwargs: Any) -> OutlineDraft:
        return OutlineDraft(sections=["One"], notice="")

    monkeypatch.setattr(node_module, "ainvoke_structured", empty_draft)
    events: list[Any] = []
    no_material = await node_module.outline(
        _state(transcript="", instruction="add Poland"), writer=events.append
    )
    revision_cap = await node_module.outline(
        _state(revisions=MAX_REVISION_ROUNDS + 1, instruction="add Poland"),
        writer=events.append,
    )
    model_refusal = await node_module.outline(
        _state(revisions=1, instruction="add Poland"), writer=events.append
    )

    monkeypatch.setattr(node_module, "ainvoke_structured", full_draft)
    normal = await node_module.outline(
        _state(instruction="add Poland"), writer=events.append
    )

    assert no_material["instruction"] == ""
    assert revision_cap["instruction"] == ""
    assert model_refusal["instruction"] == ""
    assert normal["instruction"] == ""


@pytest.mark.anyio
async def test_human_prompt_carries_transcript_outline_and_revision_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> OutlineDraft:
        received["prompt"] = prompt
        received["messages"] = messages
        return OutlineDraft(sections=["One"], notice="")

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)
    events: list[Any] = []

    await node_module.outline(
        _state(outline=["Old one", "Old two"], revisions=1, instruction="add Poland"),
        writer=events.append,
    )
    revision_prompt = received["messages"][0].text()
    await node_module.outline(_state(), writer=events.append)
    fresh_prompt = received["messages"][0].text()

    assert isinstance(received["messages"][0], HumanMessage)
    assert TRANSCRIPT in revision_prompt
    assert "Current outline:" in revision_prompt
    assert "1. Old one" in revision_prompt
    assert "2. Old two" in revision_prompt
    assert "Revision instruction:" in revision_prompt
    assert "add Poland" in revision_prompt
    assert "Current outline:" not in fresh_prompt
    assert "Revision instruction:" not in fresh_prompt
    assert TRANSCRIPT in fresh_prompt
