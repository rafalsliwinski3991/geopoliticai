"""LLM helper functions in a LangChain structured-output chain style."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Type

from langchain_core.prompts import ChatPromptTemplate
from openai import OpenAI
from pydantic import BaseModel

from geopoliticai.config import get_model

logger = logging.getLogger(__name__)
_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


@dataclass
class StructuredOutputChain:
    """Prompt + schema chain with invoke(), similar to LangChain runnable style."""

    schema: Type[BaseModel]
    system_prompt: str
    human_prompt: str
    temperature: float = 0.0

    def invoke(self, variables: dict[str, Any]) -> BaseModel:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("human", self.human_prompt),
            ]
        )
        messages = prompt.format_messages(**variables)
        client = get_openai_client()
        model = get_model()
        logger.info(
            "LLM structured request: model=%s temp=%.2f schema=%s",
            model,
            self.temperature,
            self.schema.__name__,
        )
        try:
            response = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": messages[0].content},
                    {"role": "user", "content": messages[1].content},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            payload = json.loads(response.output_text)
        except TypeError:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": messages[0].content},
                    {"role": "user", "content": messages[1].content},
                ],
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            payload = json.loads(response.choices[0].message.content)
        return self.schema.model_validate(payload)


def invoke_structured_chain(
    *,
    schema: Type[BaseModel],
    system_prompt: str,
    human_prompt: str,
    variables: dict[str, Any],
    temperature: float = 0.0,
) -> BaseModel:
    chain = StructuredOutputChain(
        schema=schema,
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        temperature=temperature,
    )
    return chain.invoke(variables)
