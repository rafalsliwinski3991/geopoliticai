"""Expert agent's own hardcoded config, separate from its editorial policy.

Editorial policy (which domains, how they're batched, paywall handling) lives
in `agents/expert/consts/sources.py`. This module holds pipeline sizing and
the per-node LLM settings, edited here directly rather than read from the
environment.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import LLMSettings

ANSWER_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout_seconds=60.0,
    max_output_tokens=16_384,
)


@dataclass(frozen=True)
class RetrievalSettings:
    """How many candidates/sources the pipeline carries between nodes."""

    fetch_candidates: int = 10
    keep_sources: int = 8


RETRIEVAL = RetrievalSettings()
