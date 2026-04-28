from typing import Any, ClassVar

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel

import llm


class SampleOutput(BaseModel):
    synthesis: str


class _FakeChatOpenAI:
    calls: ClassVar[list[dict[str, Any]]] = []
    schemas: ClassVar[list[type[BaseModel]]] = []
    inputs: ClassVar[list[Any]] = []
    response: ClassVar[Any] = SampleOutput(synthesis="ok")

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def with_structured_output(self, schema: type[BaseModel]) -> Any:
        self.schemas.append(schema)

        def _invoke_structured(prompt_value: Any) -> Any:
            self.inputs.append(prompt_value)
            response = self.response
            if isinstance(response, list):
                response = response.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        return _invoke_structured


def _reset_fake_chat_openai(response: Any = None) -> None:
    _FakeChatOpenAI.calls = []
    _FakeChatOpenAI.schemas = []
    _FakeChatOpenAI.inputs = []
    _FakeChatOpenAI.response = (
        SampleOutput(synthesis="ok") if response is None else response
    )


def test_invoke_structured_chain_uses_chat_openai_structured_output(
    monkeypatch,
) -> None:
    _reset_fake_chat_openai()
    monkeypatch.setattr(llm, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(llm, "get_openai_max_output_tokens", lambda: 321)
    monkeypatch.setattr(llm, "get_openai_timeout_seconds", lambda: 12.5)

    result = llm.invoke_structured_chain(
        schema=SampleOutput,
        system_prompt="System for {topic}",
        human_prompt="Human for {topic}",
        variables={"topic": "NATO"},
        temperature=0.2,
        model="gpt-4o-mini",
    )

    assert result == SampleOutput(synthesis="ok")
    assert _FakeChatOpenAI.calls == [
        {
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "max_completion_tokens": 321,
            "timeout": 12.5,
        }
    ]
    assert _FakeChatOpenAI.schemas == [SampleOutput]
    messages = _FakeChatOpenAI.inputs[0].to_messages()
    assert [message.content for message in messages] == [
        "System for NATO",
        "Human for NATO",
    ]


def test_structured_output_chain_validates_mapping_results(monkeypatch) -> None:
    _reset_fake_chat_openai({"synthesis": "validated"})
    monkeypatch.setattr(llm, "ChatOpenAI", _FakeChatOpenAI)

    result = llm.StructuredOutputChain(
        schema=SampleOutput,
        system_prompt="System",
        human_prompt="Human",
        model="gpt-4o-mini",
    ).invoke({})

    assert result == SampleOutput(synthesis="validated")


def test_structured_output_chain_retries_when_output_hits_length_limit(
    monkeypatch,
) -> None:
    _reset_fake_chat_openai(
        [
            OutputParserException(
                "Could not parse response content as the length limit was reached"
            ),
            SampleOutput(synthesis="retried"),
        ]
    )
    monkeypatch.setattr(llm, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(llm, "get_openai_max_output_tokens", lambda: 100)

    result = llm.StructuredOutputChain(
        schema=SampleOutput,
        system_prompt="System",
        human_prompt="Human",
        model="gpt-4o-mini",
    ).invoke({})

    assert result == SampleOutput(synthesis="retried")
    assert [call["max_completion_tokens"] for call in _FakeChatOpenAI.calls] == [
        100,
        200,
    ]
