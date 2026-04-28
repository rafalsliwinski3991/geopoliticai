"""LLM helper functions in a LangChain structured-output chain style."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Type

from langchain_core.prompts import ChatPromptTemplate
from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from config import (
    get_model,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)

logger = logging.getLogger(__name__)
_openai_client: OpenAI | None = None


def _is_temperature_unsupported_error(message: str) -> bool:
    """Return whether API error text indicates temperature is unsupported."""
    lowered = (message or "").lower()
    if "temperature" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "unsupported value",
            "does not support",
            "only the default (1) value is supported",
        )
    )


def _obj_get(value: Any, key: str) -> Any:
    """Read key from dict-like or attribute-like objects."""
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _extract_text_from_responses_response(response: Any) -> str:
    """Extract textual content from a Responses API payload."""
    output_text = _obj_get(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    for output_item in _obj_get(response, "output") or []:
        for content_part in _obj_get(output_item, "content") or []:
            part_text = _obj_get(content_part, "text")
            if isinstance(part_text, str) and part_text.strip():
                chunks.append(part_text.strip())
                continue
            if isinstance(part_text, dict):
                serialized = json.dumps(part_text, ensure_ascii=False).strip()
                if serialized:
                    chunks.append(serialized)
                    continue

            parsed_json = _obj_get(content_part, "json")
            if parsed_json is None:
                parsed_json = _obj_get(content_part, "parsed")
            if parsed_json is not None:
                chunks.append(json.dumps(parsed_json, ensure_ascii=False))
    return "\n".join(chunks).strip()


def _extract_text_from_chat_completions_response(response: Any) -> str:
    """Extract textual content from a Chat Completions payload."""
    choices = _obj_get(response, "choices") or []
    if not choices:
        return ""
    message = _obj_get(choices[0], "message")
    content = _obj_get(message, "content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for part in content:
        part_text = _obj_get(part, "text")
        if isinstance(part_text, str) and part_text.strip():
            chunks.append(part_text.strip())
    return "\n".join(chunks).strip()


def _loads_json_object(raw_text: str) -> dict[str, Any]:
    """Parse a JSON object from a raw model response string."""
    candidates = [raw_text.strip()]

    fenced_blocks = re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        raw_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw_text[start : end + 1].strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    preview = raw_text[:240].replace("\n", "\\n")
    raise ValueError(f"OpenAI returned non-JSON content: {preview}")


def get_openai_client() -> OpenAI:
    """Return a lazily initialized OpenAI client."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _create_chat_completion_with_retries(
    *,
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    max_output_tokens: int,
    temperature: float,
    response_format: dict[str, str] | None,
) -> Any:
    """Create a chat completion with compatibility retries for token and temperature params."""
    chat_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "timeout": timeout,
    }
    if response_format is not None:
        chat_kwargs["response_format"] = response_format

    use_max_completion_tokens = True
    for _ in range(4):
        request_kwargs = dict(chat_kwargs)
        token_key = (
            "max_completion_tokens" if use_max_completion_tokens else "max_tokens"
        )
        request_kwargs[token_key] = max_output_tokens
        try:
            return client.chat.completions.create(**request_kwargs)
        except BadRequestError as exc:
            lowered_error = str(exc).lower()
            if (
                use_max_completion_tokens
                and "max_completion_tokens" in lowered_error
                and "unsupported" in lowered_error
            ):
                use_max_completion_tokens = False
                continue
            if (
                _is_temperature_unsupported_error(lowered_error)
                and "temperature" in chat_kwargs
            ):
                chat_kwargs.pop("temperature", None)
                continue
            raise
    raise ValueError("OpenAI chat completion retries exhausted.")


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
    timeout = (
        timeout_seconds if timeout_seconds is not None else get_openai_timeout_seconds()
    )
    max_output_tokens = get_openai_max_output_tokens()
    chat_messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
    try:
        response_kwargs: dict[str, Any] = {
            "model": model,
            "input": chat_messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "max_output_tokens": max_output_tokens,
            "timeout": timeout,
        }
        try:
            response = client.responses.create(**response_kwargs)
        except BadRequestError as exc:
            if not _is_temperature_unsupported_error(str(exc)):
                raise
            response_kwargs.pop("temperature", None)
            response = client.responses.create(**response_kwargs)
        text = _extract_text_from_responses_response(response)
        if text:
            return _loads_json_object(text)
        logger.warning(
            "Responses API returned no text for model=%s; falling back to chat.completions.",
            model,
        )
    except TypeError:
        pass

    response = _create_chat_completion_with_retries(
        client=client,
        model=model,
        messages=chat_messages,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    text = _extract_text_from_chat_completions_response(response)
    if not text:
        logger.warning(
            "Chat Completions returned empty body for model=%s in JSON mode; retrying without response_format.",
            model,
        )
        response = _create_chat_completion_with_retries(
            client=client,
            model=model,
            messages=chat_messages,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_format=None,
        )
        text = _extract_text_from_chat_completions_response(response)
    if not text:
        raise ValueError("OpenAI returned an empty JSON response body.")
    return _loads_json_object(text)


@dataclass
class StructuredOutputChain:
    """Prompt + schema chain with invoke(), similar to LangChain runnable style."""

    schema: Type[BaseModel]
    system_prompt: str
    human_prompt: str
    temperature: float = 0.0
    model: str | None = None

    def invoke(self, variables: dict[str, Any]) -> BaseModel:
        """Format prompts, invoke OpenAI JSON mode, and validate the response."""
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
    """Invoke a one-shot structured output chain."""
    chain = StructuredOutputChain(
        schema=schema,
        system_prompt=system_prompt,
        human_prompt=human_prompt,
        temperature=temperature,
        model=model,
    )
    return chain.invoke(variables)
