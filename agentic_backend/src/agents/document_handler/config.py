"""The document agent's hardcoded settings."""

from __future__ import annotations

from dataclasses import dataclass

from shared.config import LLMSettings

REWRITE_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini", temperature=0.0, timeout_seconds=20.0, max_output_tokens=300
)
ANSWER_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini", temperature=0.0, timeout_seconds=60.0, max_output_tokens=4_096
)


@dataclass(frozen=True)
class RetrievalSettings:
    """How much each question reads."""

    top_chunks: int = 6
    history_messages: int = 6


RETRIEVAL = RetrievalSettings()
