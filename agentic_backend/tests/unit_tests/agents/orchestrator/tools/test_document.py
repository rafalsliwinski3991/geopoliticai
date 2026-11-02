"""Unit tests for the document specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.document.config import RETRIEVAL
from agents.orchestrator.consts.progress import DOCUMENT_PROGRESS
from agents.orchestrator.state import OrchestratorContext
from agents.orchestrator.tools.document import run_document
from shared.errors import NoDocumentError
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

document_tool_module = importlib.import_module("agents.orchestrator.tools.document")

QUESTION = "What are the fees?"
ANSWER = "Fees are 5 percent [terms.txt, chunk 3]."
CHUNKS = [
    {"filename": "terms.txt", "index": 3, "text": "Fees are 5 percent."},
    {"filename": "terms.txt", "index": 4, "text": "Fees are paid monthly."},
]


async def no_search(embedding: list[float]) -> list[Any]:
    return []


DOCUMENT_CONTEXT = OrchestratorContext(filename="terms.txt", search_document=no_search)


class RecordingAskDocument:
    """Stands in for `ask_document`: remembers each call and returns a fixed answer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], Any]] = []

    async def __call__(
        self, query: str, history: list[str], search: Any
    ) -> dict[str, Any]:
        self.calls.append((query, history, search))
        return {"answer": ANSWER, "chunks": CHUNKS}


@pytest.fixture
def ask_document(monkeypatch: pytest.MonkeyPatch) -> RecordingAskDocument:
    recording = RecordingAskDocument()
    monkeypatch.setattr(document_tool_module, "ask_document", recording)
    return recording


@pytest.mark.anyio
async def test_a_question_with_no_attached_document_raises(
    ask_document: RecordingAskDocument,
) -> None:
    """The supervisor only binds this tool in a document thread; if it ever runs without one,
    the user must get the error, not an answer from nothing."""
    # Arrange
    runtime = make_tool_runtime(context=OrchestratorContext())

    # Act + Assert
    with pytest.raises(NoDocumentError):
        await run_document.ainvoke({"query": QUESTION, "runtime": runtime})
    assert ask_document.calls == []


@pytest.mark.anyio
async def test_the_tool_passes_the_question_and_recent_history(
    ask_document: RecordingAskDocument,
) -> None:
    """The rewrite step resolves "and in 2022?" only if it sees the turns before it."""
    # Arrange
    state = {
        "messages": [
            HumanMessage("Who signed it?"),
            AIMessage("Alice signed it."),
        ]
    }
    runtime = make_tool_runtime(state=state, context=DOCUMENT_CONTEXT)

    # Act
    await run_document.ainvoke({"query": QUESTION, "runtime": runtime})

    # Assert
    assert ask_document.calls == [
        (QUESTION, ["human: Who signed it?", "ai: Alice signed it."], no_search)
    ]


@pytest.mark.anyio
async def test_history_is_limited_to_the_last_messages(
    ask_document: RecordingAskDocument,
) -> None:
    """An unbounded history would grow the rewrite prompt with every turn."""
    # Arrange
    total = RETRIEVAL.history_messages + 3
    state = {"messages": [HumanMessage(f"question {n}") for n in range(total)]}
    runtime = make_tool_runtime(state=state, context=DOCUMENT_CONTEXT)

    # Act
    await run_document.ainvoke({"query": QUESTION, "runtime": runtime})

    # Assert
    history = ask_document.calls[0][1]
    assert history == [f"human: question {n}" for n in range(3, total)]


@pytest.mark.anyio
async def test_a_tool_message_contributes_its_artifact_text_to_the_history(
    ask_document: RecordingAskDocument,
) -> None:
    """A document answer lives in the tool message's artifact; its content is only a summary."""
    # Arrange
    state = {
        "messages": [
            ToolMessage(
                content="Answered from 2 excerpts.",
                tool_call_id="call_1",
                artifact={"text": "The earlier full answer."},
            )
        ]
    }
    runtime = make_tool_runtime(state=state, context=DOCUMENT_CONTEXT)

    # Act
    await run_document.ainvoke({"query": QUESTION, "runtime": runtime})

    # Assert
    assert ask_document.calls[0][1] == ["tool: The earlier full answer."]


@pytest.mark.anyio
async def test_the_tool_returns_the_answer_as_the_message_artifact(
    ask_document: RecordingAskDocument,
) -> None:
    """The supervisor's history shows the summary; the answer itself rides in the artifact."""
    # Arrange
    runtime = make_tool_runtime(
        context=DOCUMENT_CONTEXT, tool_call_id="call_document_1"
    )

    # Act
    command = await run_document.ainvoke({"query": QUESTION, "runtime": runtime})

    # Assert
    (message,) = command.update["messages"]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_document_1"
    assert message.artifact == {"text": ANSWER}
    assert message.content == (
        "Answered 'What are the fees?' from 2 excerpts of the attached document."
    )


@pytest.mark.anyio
async def test_the_tool_announces_its_progress(
    ask_document: RecordingAskDocument,
) -> None:
    """The browser shows "Searching your document..." while the lookup runs."""
    # Arrange
    emitted: list[Any] = []
    runtime = make_tool_runtime(context=DOCUMENT_CONTEXT, writer=emitted.append)

    # Act
    await run_document.ainvoke({"query": QUESTION, "runtime": runtime})

    # Assert
    assert emitted == [DOCUMENT_PROGRESS]
