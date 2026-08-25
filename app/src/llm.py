"""LLM helper functions built on LangChain outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Type, cast

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import (
    get_model,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)

DEFAULT_MAX_RETRIES = 2


class LLMInvocationError(RuntimeError):
    """Raised when a model call or its output parsing fails unrecoverably."""


@dataclass
class StructuredOutputChain:
    """Prompt + schema chain with invoke(), similar to LangChain runnable style."""

    schema: Type[BaseModel]
    system_prompt: str
    human_prompt: str
    temperature: float = 0.0
    model: str | None = None

    def invoke(self, variables: dict[str, Any]) -> BaseModel:
        """Format prompts, invoke ChatOpenAI structured output, and validate."""
        model = self.model or get_model()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("human", self.human_prompt),
            ]
        )
        llm = ChatOpenAI(
            model=model,
            temperature=self.temperature,
            max_completion_tokens=get_openai_max_output_tokens(),
            timeout=get_openai_timeout_seconds(),
            max_retries=DEFAULT_MAX_RETRIES,
        )
        try:
            result = (prompt | llm.with_structured_output(self.schema)).invoke(variables)
        except Exception as exc:
            raise LLMInvocationError(
                f"Structured call failed for schema={self.schema.__name__}"
            ) from exc

        if isinstance(result, self.schema):
            return result
        try:
            return self.schema.model_validate(cast(Any, result))
        except Exception as exc:
            raise LLMInvocationError(
                f"Structured response validation failed for schema={self.schema.__name__}"
            ) from exc


@dataclass
class TextOutputChain:
    """Prompt + plain-text model chain used for streamable final synthesis."""

    system_prompt: str
    human_prompt: str
    temperature: float = 0.0
    model: str | None = None

    def invoke(
        self,
        variables: dict[str, Any],
        config: RunnableConfig | None = None,
    ) -> str:
        """Format prompts, invoke the model, and return non-empty text content."""
        prompt = ChatPromptTemplate.from_messages(
            [("system", self.system_prompt), ("human", self.human_prompt)]
        )
        llm = ChatOpenAI(
            model=self.model or get_model(),
            temperature=self.temperature,
            max_completion_tokens=get_openai_max_output_tokens(),
            timeout=get_openai_timeout_seconds(),
            max_retries=0,
        )
        try:
            result = (prompt | llm).invoke(variables, config=config)
        except Exception as exc:
            raise LLMInvocationError("Text call failed.") from exc
        content = getattr(result, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise LLMInvocationError("Text call returned empty or non-text content.")
        return content


def invoke_structured_chain(
    *,
    schema: Type[BaseModel],
    system_prompt: str,
    human_prompt: str,
    variables: dict[str, Any],
    temperature: float = 0.0,
    model: str | None = None,
) -> BaseModel:
    """Invoke a one-shot structured output chain."""
    chain = StructuredOutputChain(
        schema=schema,
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        temperature=temperature,
        model=model,
    )
    return chain.invoke(variables)


def invoke_text_chain(
    *,
    system_prompt: str,
    human_prompt: str,
    variables: dict[str, Any],
    temperature: float = 0.0,
    model: str | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Invoke a one-shot plain-text output chain."""
    chain = TextOutputChain(
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        temperature=temperature,
        model=model,
    )
    return chain.invoke(variables, config=config)
