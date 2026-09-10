import importlib
from typing import Any, AsyncIterator

import pytest

from agents.reporter.consts.progress import REPORT_PROGRESS
from models import LLMInvocationError

node_module = importlib.import_module("agents.reporter.nodes.write")

TRANSCRIPT = "User: eastern flank?\n\nAssistant: Here it is [1](https://example.com/a)."


def _state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "transcript": TRANSCRIPT,
        "outline": ["First", "Second"],
        "notice": "",
        "instruction": "",
        "revisions": 0,
        "report": "",
    }
    state.update(overrides)
    return state


def _stub_stream(
    monkeypatch: pytest.MonkeyPatch,
    events: list[Any],
    chunks: list[str],
    received: dict[str, Any],
) -> None:
    async def stream(
        prompt: str,
        human_prompt: str,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        received["prompt"] = prompt
        received["human_prompt"] = human_prompt
        for index, chunk in enumerate(chunks):
            if index == 0:
                received["events_at_first_chunk"] = len(events)
            yield chunk
        received["fully_drained"] = True

    monkeypatch.setattr(node_module, "astream_text", stream)


@pytest.mark.anyio
async def test_progress_is_emitted_once_before_the_first_chunk_is_pulled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    received: dict[str, Any] = {}
    _stub_stream(monkeypatch, events, ["Hello ", "world."], received)

    result = await node_module.write(_state(), writer=events.append)

    assert events == [REPORT_PROGRESS]
    assert received["events_at_first_chunk"] == 1
    assert result == {"report": "Hello world."}


@pytest.mark.anyio
async def test_the_joined_stream_is_stripped_into_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    received: dict[str, Any] = {}
    _stub_stream(monkeypatch, events, ["  Padded ", "report \n"], received)

    result = await node_module.write(_state(), writer=events.append)

    assert result == {"report": "Padded report"}


@pytest.mark.anyio
async def test_an_over_long_report_is_clipped_after_the_stream_is_fully_drained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(node_module, "MAX_REPORT_CHARS", 10)
    events: list[Any] = []
    received: dict[str, Any] = {}
    _stub_stream(monkeypatch, events, ["a" * 15, "b" * 10], received)

    result = await node_module.write(_state(), writer=events.append)

    assert result["report"] == "a" * 10
    assert received["fully_drained"] is True
    assert len(result["report"]) == 10


@pytest.mark.anyio
async def test_an_empty_stream_raises_llm_invocation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    received: dict[str, Any] = {}
    _stub_stream(monkeypatch, events, ["   "], received)

    with pytest.raises(LLMInvocationError):
        await node_module.write(_state(), writer=events.append)


@pytest.mark.anyio
async def test_the_prompt_carries_the_numbered_outline_and_the_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[Any] = []
    received: dict[str, Any] = {}
    _stub_stream(monkeypatch, events, ["The report."], received)

    await node_module.write(_state(outline=["One", "Two"]), writer=events.append)

    assert "1. One" in received["human_prompt"]
    assert "2. Two" in received["human_prompt"]
    assert TRANSCRIPT in received["human_prompt"]
