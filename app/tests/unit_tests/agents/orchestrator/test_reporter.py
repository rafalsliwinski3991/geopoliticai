import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.reporter.consts.messages import CANCELLED_NOTICE, NO_MATERIAL_NOTICE

node_module = importlib.import_module("agents.orchestrator.nodes.reporter")


class _FakeChild:
    """Stands in for the compiled reporter subgraph."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._result is None:
            raise AssertionError("reporter must not invoke the subgraph on this path")
        self.calls.append(state)
        return self._result


def _chat_thread() -> list[Any]:
    return [
        HumanMessage("What is happening on the eastern flank?"),
        AIMessage("Here is the situation [1](https://example.com/a)."),
    ]


def _chat_thread_without_citations() -> list[Any]:
    return [
        HumanMessage("hello"),
        AIMessage("Hi! How can I help?"),
    ]


@pytest.mark.anyio
async def test_a_fresh_request_without_material_refuses_without_invoking_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild()
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    result = await node_module.reporter(
        {"messages": [HumanMessage("write me a report")]}, writer=events.append
    )

    assert result["messages"][0].text() == NO_MATERIAL_NOTICE
    assert events == [{"type": "notice", "text": NO_MATERIAL_NOTICE}]
    assert child.calls == []


@pytest.mark.anyio
async def test_a_chat_only_thread_without_citations_refuses_without_invoking_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild()
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    result = await node_module.reporter(
        {"messages": _chat_thread_without_citations()}, writer=events.append
    )

    assert result["messages"][0].text() == NO_MATERIAL_NOTICE
    assert events == [{"type": "notice", "text": NO_MATERIAL_NOTICE}]
    assert child.calls == []


@pytest.mark.anyio
async def test_a_thread_with_a_cited_answer_invokes_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild(
        result={"report": "The report.", "outline": ["One"], "notice": ""}
    )
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    await node_module.reporter({"messages": _chat_thread()}, writer=events.append)

    assert child.calls


@pytest.mark.anyio
async def test_the_child_receives_a_transcript_with_both_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild(
        result={"report": "The report.", "outline": ["One"], "notice": ""}
    )
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []
    messages = [
        HumanMessage("first question"),
        AIMessage("first answer [1](https://example.com)"),
    ]

    await node_module.reporter({"messages": messages}, writer=events.append)

    transcript = child.calls[0]["transcript"]
    assert "User: first question" in transcript
    assert "Assistant: first answer" in transcript


@pytest.mark.anyio
async def test_a_report_result_is_returned_and_emits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild(
        result={"report": "The report.", "outline": ["One"], "notice": ""}
    )
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    result = await node_module.reporter(
        {"messages": _chat_thread()}, writer=events.append
    )

    assert result["messages"][0].text() == "The report."
    assert events == []


@pytest.mark.anyio
async def test_a_notice_result_is_returned_and_emitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild(result={"report": "", "outline": [], "notice": "Refused."})
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    result = await node_module.reporter(
        {"messages": _chat_thread()}, writer=events.append
    )

    assert result["messages"][0].text() == "Refused."
    assert events == [{"type": "notice", "text": "Refused."}]


@pytest.mark.anyio
async def test_a_result_with_neither_report_nor_notice_returns_the_cancel_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _FakeChild(result={"report": "", "outline": [], "notice": ""})
    monkeypatch.setattr(node_module, "reporter_graph", child)
    events: list[Any] = []

    result = await node_module.reporter(
        {"messages": _chat_thread()}, writer=events.append
    )

    assert result["messages"][0].text() == CANCELLED_NOTICE
    assert events == [{"type": "notice", "text": CANCELLED_NOTICE}]
