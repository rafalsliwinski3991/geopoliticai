"""LLM helper functions built on LangChain structured outputs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Type, cast

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import (
    get_model,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)

logger = logging.getLogger(__name__)
MAX_STRUCTURED_OUTPUT_RETRY_TOKENS = 16_384
LENGTH_LIMIT_ERROR_MARKERS = (
    "length limit was reached",
    "finish_reason=length",
    "finish_reason was length",
)


def _is_length_limit_error(exc: Exception) -> bool:
    """Return whether structured output parsing failed because output was truncated."""
    message = str(exc).lower()
    return any(marker in message for marker in LENGTH_LIMIT_ERROR_MARKERS)


def _structured_output_token_limits(initial_limit: int) -> list[int]:
    """Return increasing output-token limits for retrying truncated schema JSON."""
    limits = [
        initial_limit,
        min(initial_limit * 2, MAX_STRUCTURED_OUTPUT_RETRY_TOKENS),
        MAX_STRUCTURED_OUTPUT_RETRY_TOKENS,
    ]
    deduped: list[int] = []
    for limit in limits:
        if limit > 0 and limit not in deduped:
            deduped.append(limit)
    return deduped


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
        logger.debug(
            "LLM structured request: model=%s temp=%.2f schema=%s",
            model,
            self.temperature,
            self.schema.__name__,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("human", self.human_prompt),
            ]
        )
        token_limits = _structured_output_token_limits(get_openai_max_output_tokens())
        timeout = get_openai_timeout_seconds()
        for token_limit in token_limits:
            llm = ChatOpenAI(
                model=model,
                temperature=self.temperature,
                max_completion_tokens=token_limit,
                timeout=timeout,
            )
            structured_llm = llm.with_structured_output(self.schema)
            try:
                result = (prompt | structured_llm).invoke(variables)
                break
            except Exception as exc:
                if not _is_length_limit_error(exc) or token_limit == token_limits[-1]:
                    raise
                logger.warning(
                    "Structured output for schema=%s hit token limit=%d; retrying with a larger limit.",
                    self.schema.__name__,
                    token_limit,
                )

        if isinstance(result, self.schema):
            return result
        return self.schema.model_validate(cast(Any, result))


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
