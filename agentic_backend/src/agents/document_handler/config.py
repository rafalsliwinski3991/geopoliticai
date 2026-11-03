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
    # A question about the whole document (what it is about, a summary) reads this many.
    whole_chunks: int = 20
    history_messages: int = 6


RETRIEVAL = RetrievalSettings()
