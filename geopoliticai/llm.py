"""LLM helper functions in a LangChain structured-output chain style."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Type

from langchain_core.prompts import ChatPromptTemplate
from openai import OpenAI
from pydantic import BaseModel

from geopoliticai.config import get_model, get_openai_timeout_seconds

logger = logging.getLogger(__name__)
_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def invoke_openai_json_object(
    *,
    client: OpenAI,
    model: str,
    system_content: str,
    user_content: str,
    temperature: float = 0.0,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Call OpenAI and return a parsed JSON object across SDK surfaces."""
    timeout = timeout_seconds if timeout_seconds is not None else get_openai_timeout_seconds()
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        text = response.output_text
    except TypeError:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        text = response.choices[0].message.content

    if not text:
        raise ValueError("OpenAI returned an empty JSON response body.")
    return json.loads(text)


@dataclass
class StructuredOutputChain:
    """Prompt + schema chain with invoke(), similar to LangChain runnable style."""

    schema: Type[BaseModel]
    system_prompt: str
    human_prompt: str
    temperature: float = 0.0
    model: str | None = None

    def invoke(self, variables: dict[str, Any]) -> BaseModel:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("human", self.human_prompt),
            ]
        )
        messages = prompt.format_messages(**variables)
        # OpenAI JSON mode requires that the prompt explicitly mentions JSON.
        system_content = (
            f"{messages[0].content}\n\n"
            "Output requirement: return only a valid JSON object."
        )
        user_content = str(messages[1].content)
        client = get_openai_client()
        model = self.model or get_model()
        logger.debug(
            "LLM structured request: model=%s temp=%.2f schema=%s",
            model,
            self.temperature,
            self.schema.__name__,
        )
        payload = invoke_openai_json_object(
            client=client,
            model=model,
            system_content=system_content,
            user_content=user_content,
            temperature=self.temperature,
        )
        return self.schema.model_validate(payload)


def invoke_structured_chain(
    *,
    schema: Type[BaseModel],
    system_prompt: str,
    human_prompt: str,
    variables: dict[str, Any],
    temperature: float = 0.0,
    model: str | None = None,
) -> BaseModel:
    chain = StructuredOutputChain(
        schema=schema,
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        temperature=temperature,
        model=model,
    )
    return chain.invoke(variables)
