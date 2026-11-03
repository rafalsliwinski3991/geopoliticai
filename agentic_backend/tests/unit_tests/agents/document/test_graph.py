import importlib
from typing import Any, AsyncIterator

import pytest

from agents.document import DocumentContext, ask_document, build_graph
from agents.document.nodes.retrieve import RewrittenQuery
from agents.document.state import Chunk, build_initial_document_state

retrieve_module = importlib.import_module("agents.document.nodes.retrieve")
answer_module = importlib.import_module("agents.document.nodes.answer")

QUESTION = "What does it say about fees?"
EMBEDDING = [0.25, 0.5]
CHUNK: Chunk = {"filename": "terms.txt", "index": 3, "text": "Fees are 5 percent."}


class RecordingSearch:
    """A search function that remembers every embedding it was asked about."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.embeddings: list[list[float]] = []

    async def __call__(self, embedding: list[float]) -> list[Chunk]:
        self.embeddings.append(embedding)
        return self.chunks


@pytest.fixture(autouse=True)
def scripted_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every model and the embedder are replaced; nothing here calls a provider."""

    async def rewrite(*args: Any, **kwargs: Any) -> RewrittenQuery:
        return RewrittenQuery(search_query="fee schedule")

    async def embed(text: str) -> list[float]:
        return EMBEDDING

    async def stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        yield "Fees are 5 percent "
        yield "[terms.txt, chunk 3]."

    monkeypatch.setattr(retrieve_module, "ainvoke_structured", rewrite)
    monkeypatch.setattr(retrieve_module, "embed_query", embed)
    monkeypatch.setattr(answer_module, "astream_text", stream)


@pytest.mark.anyio
async def test_the_search_function_reaches_the_node_through_the_context() -> None:
    """The thread's search is not graph state; it must arrive per run through the context."""
    # Arrange
    search = RecordingSearch([CHUNK])

    # Act
    await build_graph().ainvoke(
        build_initial_document_state(QUESTION, []),
        context=DocumentContext(search=search),
    )

    # Assert
    assert search.embeddings == [EMBEDDING]


def test_the_graph_runs_retrieve_then_answer() -> None:
    """The order is the design: an answer written before retrieval would have no excerpts."""
    # Arrange
    expected_edges = {
        ("__start__", "retrieve"),
        ("retrieve", "answer"),
        ("answer", "__end__"),
    }
    graph = build_graph()

    # Act
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    # Assert
    assert edges == expected_edges


def test_the_answer_node_is_named_answer_so_it_streams() -> None:
    """The stream only forwards text from nodes in `ANSWER_NODES`; renaming silences the answer."""
    # Arrange
    graph = build_graph()

    # Act
    nodes = set(graph.get_graph().nodes)

    # Assert
    assert "answer" in nodes


@pytest.mark.anyio
async def test_ask_document_returns_the_answer_and_the_chunks() -> None:
    """The orchestrator's tool shows the answer and keeps the chunks as its artifact."""
    # Arrange
    search = RecordingSearch([CHUNK])

    # Act
    result = await ask_document(QUESTION, [], search)

    # Assert
    assert result["answer"] == "Fees are 5 percent [terms.txt, chunk 3]."
    assert result["chunks"] == [CHUNK]


def test_the_context_can_be_described_for_studio() -> None:
    """`langgraph dev` asks for the context schema; a bare Callable field once broke it."""
    # Arrange
    graph = build_graph()

    # Act
    schema = graph.get_context_jsonschema()

    # Assert
    assert "search" not in schema.get("properties", {})
