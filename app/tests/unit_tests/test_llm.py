from collections.abc import Sequence
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

import llm
from models import LLMInvocationError


class _Result(BaseModel):
    value: str


class _State(TypedDict):
    value: str


class _StreamingFake:
    def __init__(self, chunks: Sequence[str] | None = None) -> None:
        self.messages: list[BaseMessage] | None = None
        self.chunks = chunks or ["answer"]

    async def astream(self, messages: Sequence[BaseMessage], config: Any = None) -> Any:
        self.messages = list(messages)
        for chunk in self.chunks:
            yield AIMessage(chunk)


@pytest.mark.anyio
async def test_astream_text_still_prepends_one_system_and_one_human_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _StreamingFake()
    monkeypatch.setattr(llm, "_build_client", lambda settings: fake)

    assert [chunk async for chunk in llm.astream_text("system", "human")] == ["answer"]
    assert fake.messages is not None
    assert [message.type for message in fake.messages] == ["system", "human"]
    assert [message.content for message in fake.messages] == ["system", "human"]


@pytest.mark.anyio
async def test_astream_messages_prepends_the_system_prompt_to_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _StreamingFake()
    monkeypatch.setattr(llm, "_build_client", lambda settings: fake)
    history = [HumanMessage("earlier"), AIMessage("reply")]

    [chunk async for chunk in llm.astream_messages("system", history)]

    assert fake.messages is not None
    assert fake.messages == [SystemMessage("system"), *history]


@pytest.mark.anyio
async def test_astream_messages_wraps_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingFake:
        async def astream(
            self, messages: Sequence[BaseMessage], config: Any = None
        ) -> Any:
            raise RuntimeError("provider failed")
            yield  # pragma: no cover

    monkeypatch.setattr(llm, "_build_client", lambda settings: FailingFake())

    with pytest.raises(LLMInvocationError, match="Model call failed\\."):
        [chunk async for chunk in llm.astream_messages("system", [])]


@pytest.mark.anyio
async def test_ainvoke_structured_wraps_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingFake:
        def with_structured_output(
            self, schema: type[_Result], *, method: str, strict: bool
        ) -> RunnableLambda[Any, Any]:
            return RunnableLambda(
                lambda _messages: (_ for _ in ()).throw(RuntimeError())
            )

    monkeypatch.setattr(llm, "_build_structured_client", lambda settings: FailingFake())

    with pytest.raises(LLMInvocationError, match="Structured model call failed\\."):
        await llm.ainvoke_structured("system", [], _Result)


@pytest.mark.anyio
async def test_ainvoke_structured_is_tagged_nostream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def with_structured_output(
            self, schema: type[_Result], *, method: str, strict: bool
        ) -> RunnableLambda[Any, Any]:
            return RunnableLambda(lambda _messages: _Result(value="classified"))

    monkeypatch.setattr(llm, "_build_structured_client", lambda settings: FakeClient())

    async def classify(_state: _State) -> _State:
        result = await llm.ainvoke_structured("system", [], _Result)
        return {"value": result.value}

    builder = StateGraph(_State, input_schema=_State, output_schema=_State)
    builder.add_node("classify", cast(Any, classify), input_schema=_State)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", END)
    graph = builder.compile()

    frames = [
        frame
        async for frame in graph.astream(
            cast(_State, {"value": ""}), stream_mode="messages"
        )
    ]

    assert frames == []
