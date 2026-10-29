import importlib
from typing import Any, AsyncIterator

import pytest

from agents.expert import ask_expert
from agents.expert.state import build_initial_pipeline_state
from models import Candidate, Source
from shared.errors import LLMInvocationError, NoSourcesError

expert = importlib.import_module("agents.expert")
graph_module: Any = importlib.import_module("agents.expert.graph")
retrieve_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
answer_module = importlib.import_module("agents.expert.nodes.answer")
llm_module = importlib.import_module("services.llm")


def test_graph_has_exactly_two_nodes() -> None:
    # Act
    compiled = expert.build_graph()

    # Assert
    assert set(compiled.get_graph().nodes) - {"__start__", "__end__"} == {
        "search_and_fetch",
        "answer",
    }


def test_graph_is_linear() -> None:
    # Act
    edges = {
        (edge.source, edge.target) for edge in expert.build_graph().get_graph().edges
    }

    # Assert
    assert {
        ("__start__", "search_and_fetch"),
        ("search_and_fetch", "answer"),
        ("answer", "__end__"),
    } <= edges


@pytest.mark.anyio
async def test_execution_streams_answer_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("title", "https://reuters.com/x", "reuters.com")]

    async def sources(items: list[Candidate], policy: Any) -> list[Source]:
        return [Source("title", "https://reuters.com/x", "body")]

    monkeypatch.setattr(retrieve_module, "search_allowlisted", candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", sources)
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    monkeypatch.setattr(
        llm_module,
        "_build_client",
        lambda settings: FakeListChatModel(responses=["Hello world."]),
    )
    compiled = graph_module.build_graph()
    state = build_initial_pipeline_state("question")
    config = graph_module.build_runtime_config()

    # Act
    chunks = [
        message
        async for message, metadata in compiled.astream(
            state, config=config, stream_mode="messages"
        )
        if metadata.get("langgraph_node") == "answer"
    ]

    # Assert
    assert "".join(chunk.text for chunk in chunks) == "Hello world."


@pytest.mark.anyio
async def test_execution_propagates_llm_failure_after_partial_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    async def candidates(query: str, policy: Any) -> list[Candidate]:
        return [Candidate("title", "https://reuters.com/x", "reuters.com")]

    async def sources(items: list[Candidate], policy: Any) -> list[Source]:
        return [Source("title", "https://reuters.com/x", "body")]

    monkeypatch.setattr(retrieve_module, "search_allowlisted", candidates)
    monkeypatch.setattr(retrieve_module, "fetch_sources", sources)
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk, BaseMessage
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

    class FailingChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "failing-test"

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: object,
        ) -> ChatResult:
            return ChatResult(
                generations=[ChatGeneration(message=AIMessageChunk(content="partial"))]
            )

        async def _astream(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: object,
        ) -> AsyncIterator[ChatGenerationChunk]:
            yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
            raise RuntimeError("provider failed")

    monkeypatch.setattr(
        llm_module, "_build_client", lambda settings: FailingChatModel()
    )
    compiled = graph_module.build_graph()
    state = build_initial_pipeline_state("question")
    config = graph_module.build_runtime_config()
    texts: list[str] = []

    # Act
    with pytest.raises(LLMInvocationError):
        async for message, metadata in compiled.astream(
            state, config=config, stream_mode="messages"
        ):
            if metadata.get("langgraph_node") == "answer":
                texts.append(message.text)

    # Assert
    # Already-produced chunks are yielded before the exception surfaces, so no
    # partial output is lost.
    assert "partial" in texts


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
async def test_ask_expert_returns_what_the_graph_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator's tool reads `answer` and `sources` from the graph's own
    state, so the wrapper must hand that state back untouched."""
    # Arrange
    final_state = {
        "answer": "Reply.",
        "sources": [Source("t", "https://a.example/x", "x")],
    }
    fake_graph = RecordingGraph(result=final_state)
    monkeypatch.setattr(graph_module, "graph", fake_graph)

    # Act
    result = await ask_expert("q")

    # Assert
    assert fake_graph.inputs == [
        {"query": "q", "search_query": "q", "sources": [], "answer": ""}
    ]
    assert result == final_state


@pytest.mark.anyio
async def test_ask_expert_forwards_search_query_into_initial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Polish question is searched in English, so the graph must receive both."""
    # Arrange
    fake_graph = RecordingGraph(result={"answer": "", "sources": []})
    monkeypatch.setattr(graph_module, "graph", fake_graph)

    # Act
    await ask_expert("Czym jest NATO?", search_query="What is NATO?")

    # Assert
    assert fake_graph.inputs == [
        {
            "query": "Czym jest NATO?",
            "search_query": "What is NATO?",
            "sources": [],
            "answer": "",
        }
    ]


@pytest.mark.anyio
async def test_ask_expert_lets_a_pipeline_error_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A graph failure must reach the API's error frame, not turn into an empty answer."""
    # Arrange
    monkeypatch.setattr(
        graph_module, "graph", RecordingGraph(error=NoSourcesError("no pages"))
    )

    # Act + Assert
    with pytest.raises(NoSourcesError, match="no pages"):
        await ask_expert("q")
