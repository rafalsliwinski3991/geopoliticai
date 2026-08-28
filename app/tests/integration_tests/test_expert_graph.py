import importlib
from typing import Any, AsyncIterator

import pytest

from models import Candidate, LLMInvocationError, Source

expert = importlib.import_module("agents.expert")
graph_module: Any = importlib.import_module("agents.expert.graph")
retrieve_module = importlib.import_module("agents.expert.nodes.search_and_fetch")
answer_module = importlib.import_module("agents.expert.nodes.answer")
llm_module = importlib.import_module("llm")


def test_graph_has_exactly_two_nodes() -> None:
    compiled = expert.build_graph()
    assert set(compiled.get_graph().nodes) - {"__start__", "__end__"} == {
        "search_and_fetch",
        "answer",
    }
    assert set(expert.NODE_LABELS) == {"search_and_fetch", "answer"}


def test_graph_is_linear() -> None:
    edges = {
        (edge.source, edge.target) for edge in expert.build_graph().get_graph().edges
    }
    assert {
        ("__start__", "search_and_fetch"),
        ("search_and_fetch", "answer"),
        ("answer", "__end__"),
    } <= edges


@pytest.mark.anyio
async def test_execution_emits_progress_and_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    graph_module.graph = graph_module.build_graph()
    events = [event async for event in graph_module.astream_pipeline("question")]
    assert [kind for kind, _ in events][:2] == ["progress", "progress"]
    assert "".join(text for kind, text in events if kind == "token") == "Hello world."


@pytest.mark.anyio
async def test_execution_propagates_llm_failure_after_partial_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    graph_module.graph = graph_module.build_graph()
    events: list[tuple[str, str]] = []
    with pytest.raises(LLMInvocationError):
        async for event in graph_module.astream_pipeline("question"):
            events.append(event)
    assert ("token", "partial") in events
