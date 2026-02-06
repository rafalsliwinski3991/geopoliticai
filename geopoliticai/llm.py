"""LLM helper functions."""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from geopoliticai.config import get_model

logger = logging.getLogger(__name__)
_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def llm_json(system: str, user: str, temperature: float = 0.2) -> dict:
    model = get_model()
    logger.info("LLM request: model=%s temp=%.2f", model, temperature)
    client = get_openai_client()
    try:
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.output_text)
        logger.info("LLM response received via responses API")
        return payload
    except TypeError:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
        logger.info("LLM response received via chat.completions API")
        return payload
