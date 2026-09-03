import importlib
from typing import Any, AsyncIterator

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agents.orchestrator.prompts import CHAT_SYSTEM_PROMPT
from models import LLMInvocationError

node_module = importlib.import_module("agents.orchestrator.nodes.chat")


@pytest.mark.anyio
async def test_chat_returns_one_joined_ai_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        yield " Hello "
        yield "world! \n"

    monkeypatch.setattr(node_module, "astream_messages", stream)
    result = await node_module.chat({"messages": [HumanMessage("hello")]})

    assert result == {"messages": [AIMessage("Hello world!")]}


@pytest.mark.anyio
async def test_chat_rejects_empty_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stream(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
        if False:
            yield "never"

    monkeypatch.setattr(node_module, "astream_messages", stream)
    with pytest.raises(LLMInvocationError):
        await node_module.chat({"messages": [HumanMessage("hello")]})


@pytest.mark.anyio
async def test_chat_uses_last_history_messages_and_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    async def stream(
        prompt: str,
        messages: list[Any],
        *,
        config: Any = None,
        settings: Any = None,
    ) -> AsyncIterator[str]:
        received.update(prompt=prompt, messages=messages)
        yield "answer"

    monkeypatch.setattr(node_module, "astream_messages", stream)
    messages = [HumanMessage(f"message {index}") for index in range(30)]
    await node_module.chat({"messages": messages})

    assert received["prompt"] == CHAT_SYSTEM_PROMPT
    assert "must not cite" in CHAT_SYSTEM_PROMPT
    assert len(received["messages"]) == 20
    assert received["messages"][0].content == "message 10"
