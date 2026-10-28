from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.constants import END, START, TAG_NOSTREAM
from langgraph.graph import StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from services import llm
from services.llm import build_chat_model
from shared.config import DEFAULT_LLM_SETTINGS, LLMSettings
from shared.errors import LLMInvocationError


class _Result(BaseModel):
    value: str


class _State(TypedDict):
    value: str


async def _text_stream(chunks: Sequence[str]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk


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
    # Arrange
    fake = _StreamingFake()
    monkeypatch.setattr(llm, "_build_client", lambda settings: fake)

    # Act + Assert
    assert [chunk async for chunk in llm.astream_text("system", "human")] == ["answer"]
    assert fake.messages is not None
    assert [message.type for message in fake.messages] == ["system", "human"]
    assert [message.content for message in fake.messages] == ["system", "human"]


@pytest.mark.anyio
async def test_astream_messages_prepends_the_system_prompt_to_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    fake = _StreamingFake()
    monkeypatch.setattr(llm, "_build_client", lambda settings: fake)
    history = [HumanMessage("earlier"), AIMessage("reply")]

    # Act
    [chunk async for chunk in llm.astream_messages("system", history)]

    # Assert
    assert fake.messages is not None
    assert fake.messages == [SystemMessage("system"), *history]


@pytest.mark.anyio
async def test_astream_messages_wraps_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class FailingFake:
        async def astream(
            self, messages: Sequence[BaseMessage], config: Any = None
        ) -> Any:
            raise RuntimeError("provider failed")
            yield  # pragma: no cover

    monkeypatch.setattr(llm, "_build_client", lambda settings: FailingFake())

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model call failed\\."):
        [chunk async for chunk in llm.astream_messages("system", [])]


@pytest.mark.anyio
async def test_collected_chunks_are_joined_and_stripped() -> None:
    # Arrange
    chunks = _text_stream(["  Padded ", "answer \n"])

    # Act
    text = await llm.collect_text(chunks)

    # Assert
    assert text == "Padded answer"


@pytest.mark.anyio
async def test_a_blank_stream_raises_the_default_empty_answer_message() -> None:
    # Arrange
    chunks = _text_stream(["  ", "\n"])

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model returned an empty answer\\."):
        await llm.collect_text(chunks)


@pytest.mark.anyio
async def test_a_blank_stream_raises_the_caller_empty_message() -> None:
    # Arrange
    chunks = _text_stream([])

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Model returned an empty report\\."):
        await llm.collect_text(chunks, empty_message="Model returned an empty report.")


@pytest.mark.anyio
async def test_ainvoke_structured_wraps_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    class FailingFake:
        def with_structured_output(
            self, schema: type[_Result], *, method: str, strict: bool
        ) -> RunnableLambda[Any, Any]:
            return RunnableLambda(
                lambda _messages: (_ for _ in ()).throw(RuntimeError())
            )

    monkeypatch.setattr(llm, "_build_structured_client", lambda settings: FailingFake())

    # Act + Assert
    with pytest.raises(LLMInvocationError, match="Structured model call failed\\."):
        await llm.ainvoke_structured("system", [], _Result)


@pytest.mark.anyio
async def test_ainvoke_structured_is_tagged_nostream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    configured_tags: list[list[str]] = []

    class FakeStructuredChain:
        def with_config(self, *, tags: list[str]) -> "FakeStructuredChain":
            configured_tags.append(tags)
            return self

        async def ainvoke(
            self, _messages: Sequence[BaseMessage], config: Any = None
        ) -> _Result:
            return _Result(value="classified")

    class FakeClient:
        def with_structured_output(
            self, schema: type[_Result], *, method: str, strict: bool
        ) -> FakeStructuredChain:
            return FakeStructuredChain()

    monkeypatch.setattr(llm, "_build_structured_client", lambda settings: FakeClient())

    async def classify(_state: _State) -> _State:
        result = await llm.ainvoke_structured("system", [], _Result)
        return {"value": result.value}

    builder = StateGraph(_State, input_schema=_State, output_schema=_State)
    builder.add_node("classify", cast(Any, classify), input_schema=_State)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", END)
    graph = builder.compile()

    # Act
    frames = [
        frame
        async for frame in graph.astream(
            cast(_State, {"value": ""}), stream_mode="messages"
        )
    ]

    # Assert
    assert configured_tags == [[TAG_NOSTREAM]]
    assert frames == []

    control_model = FakeListChatModel(responses=["visible"])

    async def untagged(_state: _State) -> _State:
        response = await control_model.ainvoke([HumanMessage("control")])
        return {"value": str(response.content)}

    control_builder = StateGraph(_State, input_schema=_State, output_schema=_State)
    control_builder.add_node("untagged", cast(Any, untagged), input_schema=_State)
    control_builder.add_edge(START, "untagged")
    control_builder.add_edge("untagged", END)
    control_graph = control_builder.compile()
    control_frames = [
        frame
        async for frame in control_graph.astream(
            cast(_State, {"value": ""}), stream_mode="messages"
        )
    ]

    assert control_frames


def test_build_chat_model_returns_a_non_streaming_chat_open_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    settings = LLMSettings(
        model="gpt-5-mini",
        temperature=1.0,
        timeout_seconds=120.0,
        max_output_tokens=16_384,
    )

    # Act
    client = build_chat_model(settings)

    # Assert
    assert isinstance(client, ChatOpenAI)
    assert client.streaming is False
    assert client.model_name == "gpt-5-mini"


def test_build_chat_model_passes_the_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    settings = LLMSettings(model="gpt-5-mini", reasoning_effort="low")

    # Act
    client = build_chat_model(settings)

    # Assert
    assert client.reasoning_effort == "low"


def test_build_chat_model_leaves_reasoning_effort_unset_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    # Act
    client = build_chat_model(DEFAULT_LLM_SETTINGS)

    # Assert
    assert client.reasoning_effort is None
