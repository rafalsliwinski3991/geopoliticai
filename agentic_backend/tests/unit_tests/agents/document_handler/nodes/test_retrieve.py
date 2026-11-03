import importlib
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agents.document_handler.config import RETRIEVAL
from agents.document_handler.state import Chunk, DocumentContext, DocumentState
from shared.errors import LLMInvocationError, NoDocumentError

retrieve_module = importlib.import_module("agents.document_handler.nodes.retrieve")

EMBEDDING = [0.1, 0.2]
CHUNK: Chunk = {
    "filename": "a.txt",
    "index": 1,
    "page_start": None,
    "page_end": None,
    "text": "Fees are 5 percent.",
}


class Runtime:
    """The slice of LangGraph's runtime the node reads."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.searched: list[list[float]] = []
        self.limits: list[int] = []
        self.chunks = chunks
        self.context = DocumentContext(search=self._search)

    async def _search(self, embedding: list[float], limit: int) -> list[Chunk]:
        self.searched.append(embedding)
        self.limits.append(limit)
        return self.chunks


class ScriptedRewrite:
    """Returns one scripted rewrite and records the messages it was given."""

    def __init__(
        self,
        search_query: str | Exception,
        language: str = "en",
        scope: str = "passages",
    ) -> None:
        self.search_query = search_query
        self.language = language
        self.scope = scope
        self.calls: list[list[Any]] = []
        self.configs: list[Any] = []

    async def __call__(
        self,
        system_prompt: str,
        messages: Any,
        schema: Any,
        *,
        config: Any = None,
        **_: Any,
    ) -> Any:
        self.calls.append(list(messages))
        self.configs.append(config)
        if isinstance(self.search_query, Exception):
            raise self.search_query
        return schema(
            search_query=self.search_query, language=self.language, scope=self.scope
        )


class RecordingEmbed:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def __call__(self, text: str) -> list[float]:
        self.texts.append(text)
        return EMBEDDING


def _state(history: list[str] | None = None) -> DocumentState:
    return {
        "query": "and in 2022?",
        "history": history or [],
        "search_query": "",
        "language": "",
        "chunks": [],
        "answer": "",
    }


def _install(
    monkeypatch: pytest.MonkeyPatch, rewrite: ScriptedRewrite
) -> RecordingEmbed:
    embed = RecordingEmbed()
    monkeypatch.setattr(retrieve_module, "ainvoke_structured", rewrite)
    monkeypatch.setattr(retrieve_module, "embed_query", embed)
    return embed


@pytest.mark.anyio
async def test_the_question_is_searched_by_its_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A follow-up like "and in 2022?" finds nothing alone; its rewrite does."""
    # Arrange
    embed = _install(monkeypatch, ScriptedRewrite("  fees   in 2022 "))
    runtime = Runtime([CHUNK])

    # Act
    result = await retrieve_module.retrieve(_state(), runtime)

    # Assert
    assert embed.texts == ["fees in 2022"]
    assert runtime.searched == [EMBEDDING]
    assert result == {
        "search_query": "fees in 2022",
        "language": "en",
        "chunks": [CHUNK],
    }


@pytest.mark.anyio
async def test_the_language_of_the_message_is_returned_for_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The answer model replied in English to a Polish question; the rewrite call now says which language to use."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("opłaty", language="pl"))

    # Act
    result = await retrieve_module.retrieve(_state(), Runtime([CHUNK]))

    # Assert
    assert result["language"] == "pl"


@pytest.mark.anyio
async def test_a_question_about_passages_reads_the_nearest_few_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A narrow question needs a few excerpts; more would only add cost and noise."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("fees", scope="passages"))
    runtime = Runtime([CHUNK])

    # Act
    await retrieve_module.retrieve(_state(), runtime)

    # Assert
    assert runtime.limits == [RETRIEVAL.top_chunks]


@pytest.mark.anyio
async def test_a_question_about_the_whole_document_reads_many_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "What is it about?" read 6 of 16 chunks and summarised a third of the file."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("what is it about", scope="whole"))
    runtime = Runtime([CHUNK])

    # Act
    await retrieve_module.retrieve(_state(), runtime)

    # Assert
    assert runtime.limits == [RETRIEVAL.whole_chunks]


@pytest.mark.anyio
async def test_a_whole_document_read_comes_back_in_reading_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summary written from excerpts in similarity order reads as a jumble."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("summary", scope="whole"))
    found: list[Chunk] = [
        {**CHUNK, "index": 3},
        {**CHUNK, "index": 1},
        {**CHUNK, "index": 2},
    ]

    # Act
    result = await retrieve_module.retrieve(_state(), Runtime(found))

    # Assert
    assert [chunk["index"] for chunk in result["chunks"]] == [1, 2, 3]


@pytest.mark.anyio
async def test_a_passage_read_keeps_the_order_of_similarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For a narrow question the nearest excerpt comes first, which is the one the answer leans on."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("fees", scope="passages"))
    found: list[Chunk] = [{**CHUNK, "index": 3}, {**CHUNK, "index": 1}]

    # Act
    result = await retrieve_module.retrieve(_state(), Runtime(found))

    # Assert
    assert [chunk["index"] for chunk in result["chunks"]] == [3, 1]


@pytest.mark.anyio
async def test_the_rewrite_sees_the_recent_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the last six messages are sent: older ones add cost and drift, not meaning."""
    # Arrange
    rewrite = ScriptedRewrite("q")
    _install(monkeypatch, rewrite)
    history = [f"message {n}" for n in range(8)]

    # Act
    await retrieve_module.retrieve(_state(history), Runtime([CHUNK]))

    # Assert
    sent = rewrite.calls[0][0]
    assert isinstance(sent, HumanMessage)
    assert "message 2" in sent.content and "message 7" in sent.content
    assert "message 1\n" not in sent.content
    assert "Latest message:\nand in 2022?" in sent.content


@pytest.mark.anyio
async def test_an_empty_rewrite_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Searching with an empty query returns arbitrary chunks that look like an answer."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("   "))

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await retrieve_module.retrieve(_state(), Runtime([CHUNK]))


@pytest.mark.anyio
async def test_a_failed_rewrite_never_falls_back_to_the_raw_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The repo answers a provider failure with the error, not with a weaker search."""
    # Arrange
    embed = _install(monkeypatch, ScriptedRewrite(LLMInvocationError("down")))
    runtime = Runtime([CHUNK])

    # Act + Assert
    with pytest.raises(LLMInvocationError):
        await retrieve_module.retrieve(_state(), runtime)
    assert embed.texts == []
    assert runtime.searched == []


@pytest.mark.anyio
async def test_no_matching_chunks_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A thread with no stored chunks has no document; the answer must not come from memory."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("fees"))

    # Act + Assert
    with pytest.raises(NoDocumentError):
        await retrieve_module.retrieve(_state(), Runtime([]))


@pytest.mark.anyio
async def test_the_node_receives_its_run_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LangGraph injects `config` only for some annotation spellings; a miss would drop tracing."""
    # Arrange
    rewrite = ScriptedRewrite("fees")
    _install(monkeypatch, rewrite)
    builder = StateGraph(DocumentState, context_schema=DocumentContext)
    builder.add_node("retrieve", retrieve_module.retrieve)
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", END)

    # Act
    compiled: Any = builder.compile()
    await compiled.ainvoke(
        _state(), context=DocumentContext(search=Runtime([CHUNK])._search)
    )

    # Assert
    assert rewrite.configs[0] is not None


@pytest.mark.anyio
async def test_the_search_span_records_both_queries_and_the_chunk_count(
    monkeypatch: pytest.MonkeyPatch, captured_spans: InMemorySpanExporter
) -> None:
    """A Phoenix trace alone must show what was asked, what was searched, and what came back."""
    # Arrange
    _install(monkeypatch, ScriptedRewrite("fees 2022"))

    # Act
    await retrieve_module.retrieve(_state(), Runtime([CHUNK, CHUNK]))

    # Assert
    span = next(
        s for s in captured_spans.get_finished_spans() if s.name == "document_search"
    )
    attributes = dict(span.attributes or {})
    assert attributes["document.query"] == "and in 2022?"
    assert attributes["document.search_query"] == "fees 2022"
    assert attributes["document.chunks"] == 2
    assert attributes["document.rewrite_model"] == "gpt-4o-mini"
